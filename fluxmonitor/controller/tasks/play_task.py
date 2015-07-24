
import logging
import re
import os

from fluxmonitor.err_codes import UNKNOW_COMMAND, ALREADY_RUNNING, \
    NOT_RUNNING, NO_TASK, RESOURCE_BUSY
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.config import DEBUG

from .base import CommandMixIn, DeviceOperationMixIn
from .misc import TaskLoader

logger = logging.getLogger(__name__)


class PlayTask(CommandMixIn, DeviceOperationMixIn):
    _mb_swap = None
    _hb_swap = None

    def __init__(self, server, sender, task_file):
        self.server = server
        self.connect()

        settings = CommonMetadata()
        self._bufsize = settings.play_bufsize

        self._task_file = TaskLoader(task_file)
        self._task_total = os.fstat(task_file.fileno()).st_size
        self._task_executed = 0
        self._task_in_queue = 0
        self.server.add_loop_event(self)
        logger.info("Start task with size %i", (self._task_total))

        self._status = "RUNNING"
        self.next_cmd()

    def on_exit(self, sender):
        self.server.remove_loop_event(self)
        self._task_file.close()
        self.disconnect()

    def next_cmd(self):
        while self._task_in_queue < self._bufsize:
            buf = self._task_file.readline()
            if not buf:
                if self._task_in_queue == 0:
                    self.clean_task()
                    logger.debug("Play completed")
                return

            self._task_executed += len(buf)
            if DEBUG:
                logger.debug("GCODE: %s" % buf.decode("ascii").strip())

            cmd = buf.split(b";", 1)[0].rstrip()

            if cmd:
                self.send_cmd(cmd)

    def send_cmd(self, cmd):
        # TODO:
        if cmd.startswith(b"H"):
            self._uart_hb.send(cmd[1:] + b"\n")
        else:
            self._uart_mb.send(cmd + b"\n")
            self._task_last = cmd
            self._task_in_queue += 1

    def clean_task(self):
        self._status = "COMPLETED"

    def on_mainboard_message(self, sender):
        buf = sender.obj.recv(4096)
        if self._mb_swap:
            self._mb_swap += buf.decode("ascii", "ignore")
        else:
            self._mb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._mb_swap)
        self._mb_swap = messages.pop()
        for msg in messages:
            if DEBUG:
                logger.debug("MB: %s" % msg)
            if msg.startswith("ok"):
                if self._task_in_queue is not None:
                    self._task_in_queue -= 1

        if self._status == "RUNNING":
            self.next_cmd()

    def on_headboard_message(self, sender):
        buf = sender.obj.recv(4096)
        if self._hb_swap:
            self._hb_swap += buf.decode("ascii", "ignore")
        else:
            self._hb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._hb_swap)
        self._hb_swap = messages.pop()
        for msg in messages:
            if DEBUG:
                logger.debug("HB: %s" % msg)

    def dispatch_cmd(self, cmd, sender):
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
                self.server.exit_task(self)
                return "ok"
            else:
                raise RuntimeError(RESOURCE_BUSY)

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def on_loop(self, sender):
        self.server.renew_timer()
