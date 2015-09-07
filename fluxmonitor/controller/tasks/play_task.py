
import logging
import json
import re
import os

from fluxmonitor.err_codes import UNKNOW_COMMAND, ALREADY_RUNNING, \
    NOT_RUNNING, NO_TASK, RESOURCE_BUSY
from fluxmonitor.code_executor.fcode_executor import FcodeExecutor
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

        self.executor = FcodeExecutor(self._uart_mb, self._uart_hb, task_file,
                                      settings.play_bufsize)
        self.server.add_loop_event(self)
        # self._task_file = TaskLoader(task_file)
        # self._task_total = os.fstat(task_file.fileno()).st_size
        # self._task_executed = 0
        # self._task_in_queue = 0
        # logger.info("Start task with size %i", (self._task_total))
        #
        # self._status = "RUNNING"
        # self.next_cmd()

    def on_exit(self, sender):
        self.server.remove_loop_event(self)
        self._task_file.close()
        self.disconnect()

    def on_mainboard_message(self, sender):
        buf = sender.obj.recv(4096)
        if self._mb_swap:
            self._mb_swap += buf.decode("ascii", "ignore")
        else:
            self._mb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._mb_swap)
        self._mb_swap = messages.pop()
        for msg in messages:
            self.executor.on_mainboard_message(msg)

    def on_headboard_message(self, sender):
        buf = sender.obj.recv(4096)
        if self._hb_swap:
            self._hb_swap += buf.decode("ascii", "ignore")
        else:
            self._hb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._hb_swap)
        self._hb_swap = messages.pop()
        for msg in messages:
            self.executor.on_headboard_message(msg)

    def dispatch_cmd(self, cmd, sender):
        if cmd == "report":
            return json.dumps(self.executor.get_status())

        elif cmd == "pause":
            if self.executor.pause("USER_OPERATION"):
                return "ok"
            else:
                raise RuntimeError(RESOURCE_BUSY)

        elif cmd == "resume":
            if self.executor.resume():
                return "ok"
            else:
                raise RuntimeError(RESOURCE_BUSY)

        elif cmd == "abort":
            if self.executor.abort("USER_OPERATION"):
                return "ok"
                raise RuntimeError(RESOURCE_BUSY)

        elif cmd == "quit":
            if self.executor.is_closed():
                self.server.exit_task(self)
                return "ok"
            else:
                raise RuntimeError(RESOURCE_BUSY)

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def on_loop(self, sender):
        self.server.renew_timer()
        if not self.executor.is_closed():
            self.executor.on_loop(sender)
