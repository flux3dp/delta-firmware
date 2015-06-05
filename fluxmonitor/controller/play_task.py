
import logging
import re
import os

from fluxmonitor.config import DEBUG
from fluxmonitor.err_codes import UNKNOW_COMMAND, UNKNOW_ERROR, \
    ALREADY_RUNNING, NOT_RUNNING, NO_TASK, RESOURCE_BUSY

from .tasks_base import DeviceOperationMixIn

logger = logging.getLogger(__name__)


class PlayTask(DeviceOperationMixIn):
    def __init__(self, server, sender, task_file):
        self.server = server

        try:
            self.connect()
        except:
            self.disconnect()
            raise

        self._task_file = task_file
        self._task_total = os.fstat(task_file.fileno()).st_size
        self._task_executed = 0
        self._task_in_queue = 0
        logger.info("Start task with size %i", (self._task_total))

        self._status = "RUNNING"
        self.next_cmd()

    def next_cmd(self):
        while self._task_in_queue < 2:
            buf = self._task_file.readline()
            if buf is None:
                self._clean_task()
                return

            self._task_executed += len(buf)
            if DEBUG:
                logger.debug("GCODE: %s" % buf.decode("ascii").strip())

            cmd = buf.split(b";", 1)[0].rstrip()

            if cmd:
                self._uart_mb.send(cmd + b"\n")
                self._task_last = cmd
                self._task_in_queue += 1

    def clean_task(self):
        self._status = "COMPLETED"

    def on_mainboard_message(self, sender):
        buf = sender.obj.recv(4096)
        messages = buf.decode("ascii")

        for msg in re.split("\r\n|\n", messages):
            if DEBUG:
                logger.debug("MB: %s" % msg)
            if msg.startswith("ok"):
                if self._task_in_queue is not None:
                    self._task_in_queue -= 1

        if self._status == "RUNNING":
            self.next_cmd()

    def on_headboard_message(self, sender):
        pass

    def on_message(self, message, sender):
        try:
            cmd = message.rstrip(b"\x00").decode("utf8", "ascii")
            response = self.dispatch_cmd(cmd)
            sender.send(response.encode())
        except RuntimeError as e:
            sender.send(("error %s" % e.args[0]).encode())
        except Exception as e:
            if DEBUG:
                sender.send(b"error %s %s" % (UNKNOW_ERROR, e))
            else:
                sender.send(b"error %s" % UNKNOW_ERROR)

            logger.exception(UNKNOW_ERROR)

    def dispatch_cmd(self, cmd):
        if cmd == "pause":
            if self._status == "RUNNING":
                self._status = "PAUSE"
                return "ok"
            else:
                raise RuntimeError(NOT_RUNNING)

        elif cmd == "report" or cmd == "r":
            return "%s/%i/%i/%s" % (self._status, self._task_executed,
                                    self._task_total, self._task_last)

        elif cmd == "resume":
            if self._status == "PAUSE":
                self._status = "RUNNING"
                self.next_cmd()
                return "ok"
            elif self._status == "RUNNING":
                raise RuntimeError(ALREADY_RUNNING)
            else:
                raise RuntimeError(NO_TASK)

        elif cmd == "abort":
            if self._status in ["RUNNING", "PAUSE"]:
                self._status = "ABORT"
                return "ok"
            else:
                raise RuntimeError(NO_TASK)

        elif cmd == "quit":
            if self._status in ["ABORT", "COMPLETED"]:
                self.server.exit_task()
                return "ok"
            else:
                raise RuntimeError(RESOURCE_BUSY)

        else:
            raise RuntimeError(UNKNOW_COMMAND)

    def on_loop(self, sender):
        pass
