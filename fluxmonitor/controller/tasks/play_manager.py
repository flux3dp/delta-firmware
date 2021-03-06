
from subprocess import Popen, PIPE
from tempfile import mktemp
from signal import SIGKILL
from select import select
import logging
import socket
import os

from fluxmonitor.player.connection import create_mainboard_socket
from fluxmonitor.player.base import (ST_COMPLETED, ST_ABORTED,
                                     ST_PAUSED, ST_RUNNING)
from fluxmonitor.misc.fcode_file import FCodeFile, FCodeError
from fluxmonitor.misc.pidfile import load_pid
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.err_codes import FILE_BROKEN, NOT_SUPPORT, RESOURCE_BUSY, \
    SUBSYSTEM_ERROR, UNKNOWN_ERROR
from fluxmonitor.config import PLAY_ENDPOINT
from fluxmonitor.storage import Storage, metadata

logger = logging.getLogger("Player")


def poweroff_led():
    tunnel = create_mainboard_socket()
    tunnel.send("\n@DISABLE_LINECHECK\nX5S83\n")


def clean_led():
    tunnel = create_mainboard_socket()
    tunnel.send("\n@DISABLE_LINECHECK\nX5S0\n")


class PlayerManager(object):
    alive = True
    _sock = None

    def __init__(self, loop, taskfile, terminated_callback=None):
        storage = Storage("run")

        oldpid = load_pid(storage.get_path("fluxplayerd.pid"))
        if oldpid is not None:
            try:
                os.kill(oldpid, SIGKILL)
                logger.error("Kill old player process: %i", oldpid)
            except Exception:
                logger.exception("Error while kill old process: %i", oldpid)

        s = create_mainboard_socket()
        try:
            s.send("\n@DISABLE_LINECHECK\nX5S115\n")

            if os.path.exists(PLAY_ENDPOINT):
                os.unlink(PLAY_ENDPOINT)
            ff = FCodeFile(taskfile)

            self.playinfo = ff.metadata, ff.image_buf

            cmd = ["fluxplayer", "-c", PLAY_ENDPOINT, "--task", taskfile,
                   "--log", storage.get_path("fluxplayerd.log"), "--pid",
                   storage.get_path("fluxplayerd.pid")]
            if logger.getEffectiveLevel() <= 10:
                cmd += ["--debug"]

            f = open(storage.get_path("fluxplayerd.err.log"), "a")
            proc = Popen(cmd, stdin=PIPE, stderr=f.fileno())
            child_watcher = loop.child(proc.pid, False, self.on_process_dead,
                                       terminated_callback)
            child_watcher.start()
            metadata.update_device_status(1, 0, "N/A", err_label="")

            self.child_watcher = child_watcher
            self.proc = proc

        except FCodeError as e:
            s.send("X5S0\n")
            raise RuntimeError(FILE_BROKEN, *e.args)
        except Exception as e:
            s.send("X5S0\n")
            raise RuntimeError(UNKNOWN_ERROR)
        finally:
            s.close()

    def __del__(self):
        if self.child_watcher:
            self.child_watcher.stop()
            self.child_watcher.data = None
        self.proc = None
        self._sock = None
        self.alive = False

    @property
    def label(self):
        return "Playing"

    @property
    def sock(self):
        if self._sock is None:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                s.bind(mktemp())
                s.connect(PLAY_ENDPOINT)
                s.settimeout(1.0)
                self._sock = s
            except socket.error as e:
                logger.debug("Player manager connection error: %r", e)
                st = metadata.format_device_status
                if st["st_id"] == 1 and time() - st["timestamp"] < 60:
                    raise RuntimeError(RESOURCE_BUSY)
                raise SystemError(SUBSYSTEM_ERROR)

        # Ensure no data in buffer!!
        while select((self._sock, ), (), (), 0)[0]:
            self._sock.recv(4096)

        return self._sock

    def __enter__(self):
        return self.sock

    def __exit__(self, type, value, traceback):
        pass

    def on_process_dead(self, watcher, revent):
        logger.info("Player %i quit: %i", self.proc.pid, watcher.rstatus)

        # This code is use for debug only
        try:
            os.kill(self.proc.pid, 0)
            logger.error("Player %i still alive!", self.proc.pid)
            os.kill(self.proc.pid, SIGKILL)
        except OSError:
            pass

        metadata.update_device_status(0, 0, "N/A", err_label="")
        watcher.stop()
        if watcher.data:
            watcher.data(self)
            watcher = None

    def go_to_hell(self):
        # will be called from robot only
        raise RuntimeError(NOT_SUPPORT)

    @property
    def is_running(self):
        return metadata.device_status_id == ST_RUNNING

    @property
    def is_paused(self):
        return (metadata.device_status_id & (ST_PAUSED + 2)) == ST_PAUSED

    @property
    def is_terminated(self):
        return metadata.device_status_id in (ST_COMPLETED, ST_ABORTED)

    def pause(self):
        with self as sock:
            sock.send("PAUSE")
            return sock.recv(4096)

    def resume(self):
        with self as sock:
            sock.send("RESUME")
            return sock.recv(4096)

    def abort(self):
        with self as sock:
            sock.send("ABORT")
            return sock.recv(4096)

    def set_toolhead_operating(self):
        with self as sock:
            sock.send("SET_TH_OPERATING")
            return sock.recv(4096)

    def set_toolhead_standby(self):
        with self as sock:
            sock.send("SET_TH_STANDBY")
            return sock.recv(4096)

    def load_filament(self, index):
        with self as sock:
            sock.send("LOAD_FILAMENT %s" % index)
            return sock.recv(4096)

    def unload_filament(self, index):
        with self as sock:
            sock.send("UNLOAD_FILAMENT %s" % index)
            return sock.recv(4096)

    def set_toolhead_header(self, index, temp):
        with self as sock:
            sock.send("SET_TOOLHEAD_HEATER %i %.1f" % (index, temp))
            return sock.recv(4096)

    def press_button(self):
        with self as sock:
            sock.send("INTERRUPT_LOAD_FILAMENT")
            return sock.recv(4096)

    def report(self):
        try:
            with self as sock:
                sock.send("REPORT")
                return sock.recv(4096)
        except RuntimeError:
            st_id = metadata.device_status_id
            if st_id == 1:
                return '{"st_label": "INIT", "st_id": 1}'
            elif st_id in (64, 128):
                return '{"st_label": "IDLE", "st_id": 0}'
        except SystemError:
            raise RuntimeError(SUBSYSTEM_ERROR)
        except socket.error as e:
            st = metadata.format_device_status
            if st["st_id"] == 128 and time() - st["timestamp"] < 15:
                raise RuntimeError(RESOURCE_BUSY)

            logger.error("Player socket error: %s", e)
            raise RuntimeError(SUBSYSTEM_ERROR)

    def quit(self):
        if self.proc.poll() is None:
            try:
                with self as sock:
                    sock.send("QUIT")
                    return sock.recv(4096)
            except socket.error as e:
                logger.error("Player socket error: %s", e)
                self.terminate()
                raise RuntimeError(SUBSYSTEM_ERROR)
            except Exception:
                logger.exception("Error while trying quit player")
                self.terminate()
                raise RuntimeError(SUBSYSTEM_ERROR)
        else:
            if self.child_watcher and self.child_watcher.data:
                self.child_watcher.data(self)
            return "ok"

    def on_fatal_error(self, log=""):
        logger.error("%s (Proc still alive)", log)
        self.terminate()

    def terminate(self):
        self.proc.kill()
