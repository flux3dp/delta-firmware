
from shlex import split as shlex_split
from shutil import copyfile
import logging
import socket
import json
import os
import re

import pyev

from fluxmonitor.storage import Metadata, UserSpace
from fluxmonitor.services.base import ServiceBase

from .fcode_executor import FcodeExecutor
from .connection import create_mainboard_socket, create_headboard_socket
from .options import Options
from .misc import TaskLoader


logger = logging.getLogger("")


def parse_float(str_val):
    try:
        return float(str_val)
    except (ValueError, TypeError):
        return float("NAN")


class Player(ServiceBase):
    _mb_swap = _hb_swap = None

    def __init__(self, options):
        super(Player, self).__init__(logger)

        try:
            os.nice(-5)
        except Exception:
            logger.error("Can not renice process to -5")

        self.prepare_control_socket(options.control_endpoint)
        self.meta = Metadata()

        main_sock = create_mainboard_socket()
        head_sock = create_headboard_socket()

        self.main_watcher = self.loop.io(main_sock, pyev.EV_READ,
                                         self.on_mainboard_message, main_sock)
        self.main_watcher.start()
        self.head_watcher = self.loop.io(head_sock, pyev.EV_READ,
                                         self.on_headboard_message, head_sock)
        self.head_watcher.start()

        self.timer_watcher = self.loop.timer(0.8, 0.8, self.on_timer)
        self.timer_watcher.start()

        try:
            taskfile = open(options.taskfile, "rb")
        except IOError:
            raise SystemError("Can not open task file.")

        taskloader = TaskLoader(taskfile)

        exec_opt = None
        if taskloader.error_symbol:
            exec_opt = Options()

        else:
            exec_opt = Options(taskloader)

            try:
                self.place_recent_file(options.taskfile)
            except Exception:
                logger.exception("Can not place recent file")

        self.executor = FcodeExecutor(main_sock, head_sock, taskloader,
                                      exec_opt)

        self.travel_dist = parse_float(taskloader.metadata.get("TRAVEL_DIST"))
        self.time_cose = parse_float(taskloader.metadata.get("TIME_COST"))
        self.avg_speed = self.travel_dist / self.time_cose

    def prepare_control_socket(self, endpoint):
        if not endpoint:
            logger.warn("Control endpoit not set, use default /tmp/.player")
            endpoint = "/tmp/.player"

        try:
            if os.path.exists(endpoint):
                os.unlink(endpoint)

            cmd_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            cmd_sock.bind(endpoint)
            self.cmd_watcher = self.loop.io(cmd_sock, pyev.EV_READ,
                                            self.on_cmd_message, cmd_sock, -1)
            self.cmd_watcher.start()
        except Exception:
            logger.exception("Error while listen endpoint at %s")
            raise

    def place_recent_file(self, filename):
        space = UserSpace()
        use_swap = False
        if not os.path.exists(space.get_path("SD", "Recent")):
            os.makedirs(space.get_path("SD", "Recent"))

        if os.path.abspath(filename). \
                startswith(space.get_path("SD", "Recent/recent-")):
            userspace_filename = "Recent/" + os.path.split(filename)[-1]
            space.mv("SD", userspace_filename, "Recent/swap.fc")
            filename = space.get_path("SD", "Recent/swap.fc")
            use_swap = True

        def place_file(syntax, index):
            name = syntax % index
            if space.exist("SD", name):
                if index >= 5:
                    space.rm("SD", name)
                else:
                    place_file(syntax, index + 1)
                    space.mv("SD", name, syntax % (index + 1))

        place_file("Recent/recent-%i.fc", 1)
        if use_swap:
            space.mv("SD", "Recent/swap.fc", "Recent/recent-1.fc")
        elif space.in_entry("SD", filename):
            os.link(filename,
                    space.get_path("SD", "Recent/recent-1.fc"))
        else:
            copyfile(filename,
                     space.get_path("SD", "Recent/recent-1.fc"))
        os.system("sync")

    def on_start(self):
        pass

    def on_shutdown(self):
        self.cmd_watcher.stop()
        self.cmd_watcher.data.close()
        self.cmd_watcher = None

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
        except IOError:
            logger.exception("Mainboard socket I/O error")
            return

        try:
            if not buf:
                logger.error("Mainboard connection broken")
                self.executor.abort("CONTROL_FAILED", "MB_CONN_BROKEN")

            if self._mb_swap:
                self._mb_swap += buf.decode("ascii", "ignore")
            else:
                self._mb_swap = buf.decode("ascii", "ignore")

            messages = re.split("\r\n|\n", self._mb_swap)
            self._mb_swap = messages.pop()
            for msg in messages:
                self.executor.on_mainboard_message(msg)
        except Exception:
            logger.exception("Process mainboard message error")

    def on_headboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
        except IOError:
            logger.exception("Headboard socket I/O error")
            return

        try:
            if not buf:
                logger.error("Headboard connection broken")
                self.executor.abort("CONTROL_FAILED", "HB_CONN_BROKEN")

            if self._hb_swap:
                self._hb_swap += buf.decode("ascii", "ignore")
            else:
                self._hb_swap = buf.decode("ascii", "ignore")

            messages = re.split("\r\n|\n", self._hb_swap)
            self._hb_swap = messages.pop()
            for msg in messages:
                self.executor.on_headboard_message(msg)
        except Exception:
            logger.exception("Process toolhead message error")

    def on_cmd_message(self, watcher, revent):
        try:
            S = watcher.data  # noqa
            argstr, R = S.recvfrom(128)
            args = shlex_split(argstr.decode("ascii", "ignore"))
            cmd = args[0]
            if cmd == "PAUSE":  # Pause
                if self.executor.pause():
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
            elif cmd == "REPORT":  # Report
                st = self.executor.get_status()
                st["traveled"] = self.executor.traveled
                st["prog"] = self.executor.traveled / self.travel_dist
                st["pos"] = self.executor.position
                pl = json.dumps(st)
                self.send_cmd_response(S, R, pl)
            elif cmd == "RESUME":  # Continue
                if self.executor.resume():
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
            elif cmd == "ABORT":  # Abort
                if self.executor.abort():
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
            elif cmd == "LOAD_FILAMENT":
                if self.executor.load_filament(int(args[1])):
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
            elif cmd == "EJECT_FILAMENT":
                if self.executor.eject_filament(int(args[1])):
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
            elif cmd == "QUIT":
                if self.executor.is_closed():
                    self.send_cmd_response(S, R, "ok")
                    self.shutdown("BYE")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
        except Exception:
            logger.exception("Unhandle error")

    def send_cmd_response(self, sock, remote, message):
        if remote:
            sock.sendto(message, remote)

    def on_timer(self, watcher, revent):
        try:
            self.executor.on_loop()

            if self.executor.error_symbol:
                e = self.executor.error_str
                err = e.encode() if isinstance(e, unicode) else e
            else:
                err = ""

            if self.executor.is_closed():
                watcher.stop()
            prog = self.executor.traveled / self.travel_dist
            self.meta.update_device_status(self.executor.status_id, prog,
                                           self.executor.head_ctrl.module, err)
        except Exception:
            logger.exception("Unhandler Error")
