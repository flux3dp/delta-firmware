
import logging

from fluxmonitor.misc import timer as T
from fluxmonitor.event_base import EventBase
from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.controller.tasks.command_task import CommandTask


STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(EventBase):
    @T.update_time
    def __init__(self, options):
        EventBase.__init__(self)
        self.debug = options.debug
        self.local_control = LocalControl(self, logger=logger)

        self.task_callstack = []
        self.this_task = None

        cmd_task = CommandTask(self)
        self.enter_task(cmd_task, None)

    @T.update_time
    def on_message(self, message, sender):
        self.this_task.on_message(message, sender)

    @T.update_time
    def renew_timer(self):
        pass

    def enter_task(self, invoke_task, return_callback):
        logger.debug("Enter %s" % invoke_task.__class__.__name__)
        self.task_callstack.append((self.this_task, return_callback))
        self.this_task = invoke_task

    def exit_task(self, task, *return_args):
        if self.this_task != task:
            raise Exception("Task not match")

        task, callback = self.task_callstack.pop()

        try:
            task.on_exit(self)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)

        try:
            callback(*return_args)
            logger.debug("Exit %s" % self.this_task.__class__.__name__)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)
        finally:
            self.this_task = task

    def each_loop(self):
        if T.time_since_update(self) > 1800:
            self.close()

    def close(self):
        self.local_control.close()
        self.running = False
