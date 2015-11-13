
import logging
import json
import re

from fluxmonitor.err_codes import UNKNOW_COMMAND, RESOURCE_BUSY
from fluxmonitor.code_executor.fcode_executor import FcodeExecutor
from fluxmonitor.storage import CommonMetadata

from .base import CommandMixIn, DeviceOperationMixIn

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
        self.timer_watcher = server.loop.timer(3, 3, self.on_timer)
        self.timer_watcher.start()

    def on_exit(self, sender):
        self.timer_watcher.stop()
        self.timer_watcher = None
        self.executor.close()
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
            else:
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

    def on_timer(self, watcher, revent):
        self.server.renew_timer()
        if not self.executor.is_closed():
            self.executor.on_loop(sender)

    def get_status(self):
        return self.executor.get_status()

    def pause(self, reason):
        return self.executor.pause(reason)

    def resume(self):
        return self.executor.resume()

    def abort(self, reason):
        return self.executor.abort(reason)
