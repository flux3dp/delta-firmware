
from subprocess import Popen, PIPE
from tempfile import mktemp
from time import time
import logging
import socket
import os

from fluxmonitor.player.connection import create_mainboard_socket
from fluxmonitor.player.base import (ST_COMPLETED, ST_ABORTED,
                                     ST_PAUSED, ST_RUNNING)
from fluxmonitor.misc.fcode_file import FCodeFile, FCodeError
from fluxmonitor.err_codes import FILE_BROKEN, NOT_SUPPORT, UNKNOWN_ERROR, \
    RESOURCE_BUSY
from fluxmonitor.config import PLAY_ENDPOINT, PLAY_SWAP
from fluxmonitor.storage import Storage, Metadata

logger = logging.getLogger("Player")


class PlayerManager(object):
    _sock = None

    def __init__(self, loop, taskfile, terminated_callback=None,
                 copyfile=False):
        self.meta = Metadata()
        s = create_mainboard_socket()

        try:
            s.send("\n@DISABLE_LINECHECK\nX5S115\n")
            if copyfile:
                ret = os.system("cp " + taskfile + " " + PLAY_SWAP)
                if ret:
                    logger.error("Copy file failed (return %i)", )
                    raise RuntimeError(UNKNOWN_ERROR, "IO_ERROR")

            if os.path.exists(PLAY_ENDPOINT):
                os.unlink(PLAY_ENDPOINT)
            ff = FCodeFile(taskfile)

            self.playinfo = ff.metadata, ff.image_buf

            storage = Storage("log")
            cmd = ["fluxplayer", "-c", PLAY_ENDPOINT, "--task", taskfile,
                   "--log", storage.get_path("fluxplayerd.log")]
            if logger.getEffectiveLevel() <= 10:
                cmd += ["--debug"]

            proc = Popen(cmd, stdin=PIPE)
            child_watcher = loop.child(proc.pid, False, self.on_process_dead,
                                       terminated_callback)
            child_watcher.start()
            self.meta.update_device_status(1, 0, "N/A", err_label="")

            self.watchers = (child_watcher, )
            self.proc = proc
            self._terminated_callback = terminated_callback

        except FCodeError as e:
            raise RuntimeError(FILE_BROKEN, *e.args)
        finally:
            s.close()

    def __del__(self):
        for w in self.watchers:
            w.stop()
            w.data = None
        self.watchers = None
        self.proc = None
        self._sock = None

    @property
    def label(self):
        return "Playing"

    @property
    def sock(self):
        if not self._sock:
            if not os.path.exists(PLAY_ENDPOINT):
                st = self.meta.format_device_status
                if st["st_id"] == 1 and time() - st["timestemp"] < 30:
                    raise RuntimeError(RESOURCE_BUSY)
                else:
                    self.on_fatal_error(log="Player control socket missing")
                    raise SystemError()
            try:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._sock.bind(mktemp())
                self._sock.connect(PLAY_ENDPOINT)
                self._sock.settimeout(1.5)
            except socket.error:
                st = self.meta.format_device_status
                if st["st_id"] == 1 and time() - st["timestemp"] < 30:
                    raise RuntimeError("RESOURCE_BUSY")
                else:
                    self.on_fatal_error(log="Can not connect to Player socket")
                    raise SystemError("")
        return self._sock

    def on_process_dead(self, watcher, revent):
        logger.debug("Player terminated")
        self.meta.update_device_status(0, 0, "N/A", err_label="")
        watcher.stop()
        try:
            if watcher.data:
                watcher.data(self)
                watcher = None
        finally:
            self._terminated_callback = None

    def go_to_hell(self):
        # will be called form robot only
        raise RuntimeError(NOT_SUPPORT)

    @property
    def is_running(self):
        return self.meta.device_status_id == ST_RUNNING

    @property
    def is_paused(self):
        return (self.meta.device_status_id & (ST_PAUSED + 2)) == ST_PAUSED

    @property
    def is_terminated(self):
        return self.meta.device_status_id in (ST_COMPLETED, ST_ABORTED)

    def pause(self):
        self.sock.send("PAUSE")
        return self.sock.recv(4096)

    def resume(self):
        self.sock.send("RESUME")
        return self.sock.recv(4096)

    def abort(self):
        self.sock.send("ABORT")
        return self.sock.recv(4096)

    def load_filament(self):
        self.sock.send("LOAD_FILAMENT")
        return self.sock.recv(4096)

    def eject_filament(self):
        self.sock.send("EJECT_FILAMENT")
        return self.sock.recv(4096)

    def report(self):
        try:
            self.sock.send("REPORT")
            return self.sock.recv(4096)
        except RuntimeError:
            return '{"st_label": "INIT", "st_id": 1}'

    def quit(self):
        self.sock.send("QUIT")
        return self.sock.recv(4096)

    def is_alive(self):
        return self.proc.poll() is None

    def on_fatal_error(self, log=""):
        if self.is_alive:
            logger.error("%s (Proc still alive)", log)
            self.terminate()
        else:
            logger.error("%s (Proc still alive)", log)

    def terminate(self):
        self.proc.kill()
