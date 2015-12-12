
from shlex import split as shlex_split
import logging
import socket
import json
import os
import re

import pyev

from fluxmonitor.config import MAINBOARD_ENDPOINT, HEADBOARD_ENDPOINT
from fluxmonitor.storage import CommonMetadata as Metadata
from fluxmonitor.services.base import ServiceBase

from .fcode_executor import FcodeExecutor
from .options import Options
from .misc import TaskLoader


logger = logging.getLogger("")


class Player(ServiceBase):
    _mb_swap = _hb_swap = None

    def __init__(self, options):
        super(Player, self).__init__(logger)

        try:
            os.nice(-5)
        except Exception:
            logger.error("Can not renice process to -5")

        taskfile = open(options.taskfile, "rb")
        taskloader = TaskLoader(taskfile)

        self.prepare_control_socket(options.control_endpoint)
        self.meta = Metadata()

        main_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        main_sock.connect(MAINBOARD_ENDPOINT)

        head_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        head_sock.connect(HEADBOARD_ENDPOINT)

        self.main_watcher = self.loop.io(main_sock, pyev.EV_READ,
                                         self.on_mainboard_message, main_sock)
        self.main_watcher.start()
        self.head_watcher = self.loop.io(head_sock, pyev.EV_READ,
                                         self.on_headboard_message, head_sock)
        self.head_watcher.start()

        options = Options(taskloader)
        self.executor = FcodeExecutor(main_sock, head_sock, taskloader,
                                      options)

        self.timer_watcher = self.loop.timer(0.8, 0.8, self.on_timer)
        self.timer_watcher.start()

    def prepare_control_socket(self, endpoint):
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

    def on_start(self):
        pass

    def on_shutdown(self):
        self.cmd_watcher.stop()
        self.cmd_watcher.data.close()
        self.cmd_watcher = None

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
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
            logger.exception("Mainboard Failed")

    def on_headboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
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
            logger.exception("Headboard Failed")

    def on_cmd_message(self, watcher, revent):
        try:
            S = watcher.data
            argstr, R = S.recvfrom(128)
            args = shlex_split(argstr.decode("ascii", "ignore"))
            cmd = args[0]
            if cmd == "PAUSE":  # Pause
                if self.executor.pause("USER_OPERATION"):
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "ERROR RESOURCE_BUSY")
            elif cmd == "REPORT":  # Report
                st = json.dumps(self.executor.get_status())
                self.send_cmd_response(S, R, st)
            elif cmd == "RESUME":  # Continue
                if self.executor.resume():
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "ERROR RESOURCE_BUSY")
            elif cmd == "ABORT":  # Abort
                if self.executor.abort("USER_OPERATION"):
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "ERROR RESOURCE_BUSY")
            elif cmd == "LOAD_FILAMENT":
                if self.executor.load_filament(int(args[1])):
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "ERROR RESOURCE_BUSY")
            elif cmd == "EJECT_FILAMENT":
                if self.executor.eject_filament(int(args[1])):
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "ERROR RESOURCE_BUSY")
            elif cmd == "QUIT":
                if self.executor.is_closed():
                    self.send_cmd_response(S, R, "ok")
                    self.shutdown("BYE")
                else:
                    self.send_cmd_response(S, R, "ERROR RESOURCE_BUSY")
        except Exception:
            logger.exception("Unhandle error")

    def send_cmd_response(self, sock, remote, message):
        if remote:
            sock.sendto(message, remote)

    def on_timer(self, watcher, revent):
        try:
            self.executor.on_loop()

            if self.executor._err_symbol:
                err = str(self.executor._err_symbol[0])
            else:
                err = ""

            if self.executor.is_closed():
                watcher.stop()

            self.meta.update_device_status(self.executor.status_id,
                                           0, self.executor.head_ctrl.module,
                                           err)
        except Exception:
            logger.exception("Unhandler Error")
