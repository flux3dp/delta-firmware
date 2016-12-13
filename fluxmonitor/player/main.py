
from shlex import split as shlex_split
from shutil import copyfile
import logging
import socket
import json
import os

import pyev

from fluxmonitor.storage import UserSpace, metadata
from fluxmonitor.services.base import ServiceBase

from .fcode_executor import FcodeExecutor
from .connection import create_mainboard_socket, create_toolhead_socket
from .options import Options
from .misc import TaskLoader


logger = logging.getLogger("")


def parse_float(str_val):
    try:
        val = float(str_val)
        return float("NAN") if val == 0 else val
    except (ValueError, TypeError):
        return float("NAN")


class Player(ServiceBase):
    def __init__(self, options):
        super(Player, self).__init__(logger)

        try:
            os.nice(-5)
        except Exception:
            logger.error("Can not renice process to -5")

        self.prepare_control_socket(options.control_endpoint)

        m_sock = create_mainboard_socket()
        t_sock = create_toolhead_socket()

        self.main_watcher = self.loop.io(m_sock, pyev.EV_READ,
                                         self.on_mainboard_recv, m_sock)
        self.main_watcher.start()
        self.head_watcher = self.loop.io(t_sock, pyev.EV_READ,
                                         self.on_toolhead_recv, t_sock)
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

        self.executor = FcodeExecutor(m_sock, t_sock, taskloader, exec_opt)

        self.travel_dist = parse_float(taskloader.metadata.get("TRAVEL_DIST"))
        if self.travel_dist == 0:
            self.travel_dist = float("NAN")
        self.time_cose = parse_float(taskloader.metadata.get("TIME_COST"))

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

    def on_mainboard_recv(self, watcher, revent):
        try:
            self.executor.on_mainboard_recv()
        except Exception:
            logger.exception("Process mainboard message error")

    def on_toolhead_recv(self, watcher, revent):
        try:
            self.executor.on_toolhead_recv()
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
            elif cmd == "SET_TH_OPERATING":
                if self.executor.set_toolhead_operation():
                    self.send_cmd_response(S, R, "ok")
                else:
                    self.send_cmd_response(S, R, "error RESOURCE_BUSY")
            elif cmd == "SET_TH_STANDBY":
                if self.executor.set_toolhead_standby():
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

            metadata.update_device_status(
                self.executor.status_id, prog,
                self.executor.toolhead.module_name or "N/A", err)

        except Exception:
            logger.exception("Unhandler Error")
