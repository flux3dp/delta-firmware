
import logging

from fluxmonitor.misc import timer as T
from fluxmonitor.event_base import EventBase
from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.controller.tasks.command_task import CommandTask
from fluxmonitor.misc.control_mutex import ControlLock, locking_status
from fluxmonitor.services.base import ServiceBase

STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(ServiceBase):
    POLL_TIMEOUT = 0.5

    @T.update_time
    def __init__(self, options):
        pid, label = locking_status()
        if pid:
            raise SystemError("Service mutex is locked")

        ServiceBase.__init__(self, logger)
        self.debug = options.debug
        self.local_control = LocalControl(self, logger=logger)

        self.task_callstack = []
        self.this_task = None

        cmd_task = CommandTask(self)
        self.enter_task(cmd_task, None)

        try:
            if options.taskfile:
                sender = NullSender()
                assert cmd_task.select_file(options.taskfile, sender,
                                            raw=True) == "ok"
                assert cmd_task.play(sender=sender) == "ok"
        except Exception:
            logger.exception("Error while setting task at init")

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

        try:
            task.on_exit(self)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)

        try:
            current_task, callback = self.task_callstack.pop()
            callback(*return_args)
            logger.debug("Exit %s" % self.this_task.__class__.__name__)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)
        finally:
            self.this_task = current_task

    def each_loop(self):
        if T.time_since_update(self) > 1800:
            self.shutdown(log="Idle")

    def on_start(self):
        self.ctrl_mutex = ControlLock("robot")
        self.ctrl_mutex.lock()

    def on_shutdown(self):
        self.running = False
        self.local_control.close()
        self.ctrl_mutex.unlock()


class NullSender(object):
    def send_text(self, *args):
        pass
