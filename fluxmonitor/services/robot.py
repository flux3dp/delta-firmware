
import logging

from fluxmonitor.misc import timer as T
from fluxmonitor.event_base import EventBase
from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.controller.interfaces.button import ButtonControl
from fluxmonitor.controller.tasks.command_task import CommandTask
from fluxmonitor.services.base import ServiceBase
from fluxmonitor.code_executor.base import ST_RUNNING, ST_PAUSED

STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(ServiceBase):
    POLL_TIMEOUT = 0.5

    @T.update_time
    def __init__(self, options):
        ServiceBase.__init__(self, logger)
        self.debug = options.debug

        self.local_control = LocalControl(self, logger=logger)
        self.button_control = ButtonControl(self, logger=logger)

        self.task_callstack = []
        self.this_task = None

        cmd_task = CommandTask(self)
        self.enter_task(cmd_task, None)

        try:
            if options.taskfile:
                sender = NullSender()
                ret = cmd_task.select_file(options.taskfile, sender, raw=True)
                ret = cmd_task.play(sender=sender)
                assert ret == "ok", "got: %s" % ret
        except Exception:
            logger.exception("Error while setting task at init")

    def on_button_control(self, message):
        task_label = self.this_task.__class__.__name__
        if task_label == "PlayTask":
            if message == "ABORT":
                self.this_task.abort("CANCELED")
            elif message == "RUNTOGL":
                st = self.this_task.get_status()["st_label"]
                if st == "PAUSED":
                    self.this_task.resume()
                elif st == "RUNNING":
                    self.this_task.pause("USER_OPERATE")

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
        pass

    def on_shutdown(self):
        self.running = False
        self.local_control.close(self)
        self.button_control.close(self)


class NullSender(object):
    def send_text(self, *args):
        pass
