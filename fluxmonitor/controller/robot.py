
import logging

from fluxmonitor.event_base import EventBase
from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.controller.common_tasks import CommandTask


STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(EventBase):
    def __init__(self, options):
        EventBase.__init__(self)
        self.debug = options.debug
        self.local_control = LocalControl(self, logger=logger)

        self.task_callstack = []
        self.this_task = None

        cmd_task = CommandTask(self)
        self.enter_task(cmd_task, None)

    def on_message(self, message, sender):
        self.this_task.on_message(message, sender)

    def enter_task(self, invoke_task, return_callback):
        logger.debug("Enter %s" % invoke_task.__class__.__name__)
        self.task_callstack.append((self.this_task, return_callback))
        self.this_task = invoke_task

    def exit_task(self, *return_args):
        task, callback = self.task_callstack.pop()

        try:
            callback(*return_args)
            logger.debug("Exit %s" % self.this_task.__class__.__name__)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)
        finally:
            self.this_task = task

    def each_loop(self):
        pass

    def close(self):
        self.local_control.close()
