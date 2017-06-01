
import logging
import json
import os

import pyev

from fluxmonitor.interfaces.player import PlayerUdpInterface
from fluxmonitor.services.base import ServiceBase
from fluxmonitor.err_codes import SUBSYSTEM_ERROR, FILE_BROKEN
from fluxmonitor.storage import metadata
from fluxmonitor.hal import tools

from .fcode_executor import FcodeExecutor
from .connection import create_mainboard_socket, create_toolhead_socket
from .options import Options
from .misc import TaskLoader, place_recent_file


logger = logging.getLogger("")


def parse_float(str_val):
    try:
        val = float(str_val)
        return float("NAN") if val == 0 else val
    except (ValueError, TypeError):
        return float("NAN")


class FatalExecutor(object):
    closed = True
    status_id = 128
    progress = float("NAN")
    toolhead_name = "N/A"

    def __init__(self, errors):
        # errors is a string list or tuple like ("SUBSYSTEM_ERROR", "HAL")
        self.errors = errors
        self.error_str = " ".join(errors)

    def start(self):
        return True

    def get_status(self):
        return {
            "st_id": 128,
            "st_label": "ABORTED",
            "error": self.errors,
            "module": "N/A"
        }

    def __getattr__(self, name):
        if name in ("pause", "resume", "abort",
                    "set_toolhead_operation",
                    "set_toolhead_standby",
                    "load_filament",
                    "unload_filament",
                    "interrupt_load_filament",
                    "set_toolhead_heater"):
            return lambda: False
        if name in ("on_mainboard_recv", "on_toolhead_recv", "on_loop",
                    "close"):
            return lambda *args, **kw: False


class Player(ServiceBase):
    def __init__(self, options):
        super(Player, self).__init__(logger)
        self.control_endpoint = options.control_endpoint
        metadata.update_device_status(1, 0, "N/A", err_label="")

        try:
            os.nice(-5)
        except Exception:
            logger.error("Can not renice process to -5")

        self.timer_watcher = self.loop.timer(0.8, 0.8, self.on_timer)

        try:
            tools.toolhead_power_off()

            m_sock = create_mainboard_socket()
            t_sock = create_toolhead_socket()

            self.main_watcher = self.loop.io(m_sock, pyev.EV_READ,
                                             self.on_mainboard_recv, m_sock)
            self.main_watcher.start()
            self.head_watcher = self.loop.io(t_sock, pyev.EV_READ,
                                             self.on_toolhead_recv, t_sock)
            self.head_watcher.start()
        except Exception:
            logger.exception("Prepare HAL connection error")
            self.executor = FatalExecutor((SUBSYSTEM_ERROR, "HAL"))
            return

        try:
            taskfile = open(options.taskfile, "rb")
            taskloader = TaskLoader(taskfile)
            exec_opt = Options(taskloader)

            try:
                place_recent_file(options.taskfile)
            except Exception:
                logger.exception("Can not place recent file")

        except (IOError, OSError, AssertionError):
            logger.exception("Open task file error")
            self.executor = FatalExecutor((FILE_BROKEN, ))
            return
        except RuntimeError as e:
            logger.error("Open task file error")
            self.executor = FatalExecutor(e.args)
            return
        except Exception:
            logger.exception("Unknown error while open taskfile")
            self.executor = FatalExecutor((SUBSYSTEM_ERROR, "TASKLOADER"))
            return

        metadata.update_device_status(1, 0, "N/A", err_label="")

        timecost = parse_float(taskloader.metadata.get("TIME_COST"))
        traveldist = parse_float(taskloader.metadata.get("TRAVEL_DIST"))
        if traveldist == 0:
            traveldist = float("NAN")
        self.executor = FcodeExecutor(m_sock, t_sock, taskloader, exec_opt,
                                      timecost=timecost, traveldist=traveldist)

    def on_start(self):
        self.control_interface = PlayerUdpInterface(self,
                                                    self.control_endpoint)
        self.timer_watcher.start()
        self.executor.start()

    def on_shutdown(self):
        self.executor.close()
        self.control_interface.close()

    def on_mainboard_recv(self, watcher, revent):
        try:
            self.executor.on_mainboard_recv()
        except Exception:
            logger.exception("Unhandle mainboard recv error")

    def on_toolhead_recv(self, watcher, revent):
        try:
            self.executor.on_toolhead_recv()
        except Exception:
            logger.exception("Unhandle toolhead recv error")

    def on_request(self, handler, endpoint, cmd, *args):
        try:
            if cmd == "PAUSE":  # Pause
                if self.executor.pause():
                    handler.sendto("ok", endpoint)
                else:
                    handler.sendto("error RESOURCE_BUSY", endpoint)
            elif cmd == "REPORT":  # Report
                st = self.executor.get_status()
                pl = json.dumps(st)
                handler.sendto(pl, endpoint)
            elif cmd == "RESUME":  # Continue
                if self.executor.resume():
                    handler.sendto("ok", endpoint)
                else:
                    handler.sendto("error RESOURCE_BUSY", endpoint)
            elif cmd == "ABORT":  # Abort
                if self.executor.soft_abort():
                    handler.sendto("ok", endpoint)
                else:
                    handler.sendto("error RESOURCE_BUSY", endpoint)
            elif cmd == "SET_TH_OPERATING":
                if self.executor.set_toolhead_operation():
                    handler.sendto("ok", endpoint)
                else:
                    handler.sendto("error RESOURCE_BUSY", endpoint)
            elif cmd == "SET_TH_STANDBY":
                if self.executor.set_toolhead_standby():
                    handler.sendto("ok", endpoint)
                else:
                    handler.sendto("error RESOURCE_BUSY", endpoint)
            elif cmd == "INTERRUPT_LOAD_FILAMENT":
                if self.executor.interrupt_load_filament():
                    return handler.sendto("ok", endpoint)
                else:
                    handler.sendto("error RESOURCE_BUSY", endpoint)
            elif cmd == "LOAD_FILAMENT":
                try:
                    if self.executor.load_filament(int(args[0])):
                        handler.sendto("ok", endpoint)
                    else:
                        handler.sendto("error RESOURCE_BUSY", endpoint)
                except (ValueError, IndexError):
                    handler.sendto("error BAD_PARAMS", endpoint)
            elif cmd == "UNLOAD_FILAMENT":
                try:
                    if self.executor.unload_filament(int(args[0])):
                        handler.sendto("ok", endpoint)
                    else:
                        handler.sendto("error RESOURCE_BUSY", endpoint)
                except (ValueError, IndexError):
                    handler.sendto("error BAD_PARAMS", endpoint)
            elif cmd == "SET_TOOLHEAD_HEATER":
                try:
                    if self.executor.set_toolhead_heater(int(args[0]),
                                                         float(args[1])):
                        handler.sendto("ok", endpoint)
                    else:
                        handler.sendto("error RESOURCE_BUSY", endpoint)
                except (ValueError, IndexError):
                    handler.sendto("error BAD_PARAMS", endpoint)
            elif cmd == "QUIT":
                if self.executor.status_id in (64, 128):
                    handler.sendto("ok", endpoint)
                    self.shutdown("BYE")
                else:
                    logger.warning("Quit request rejected because status id is"
                                   " %s", self.executor.status_id)
                    handler.sendto("error RESOURCE_BUSY", endpoint)
        except Exception:
            logger.exception("Unhandle error")

    def on_timer(self, watcher, revent):
        try:
            if self.executor.closed:
                watcher.stop()
            else:
                self.executor.on_loop()

            metadata.update_device_status(
                self.executor.status_id, self.executor.progress,
                self.executor.toolhead_name or "N/A", self.executor.error_str)

        except Exception:
            logger.exception("Unhandler Error")
