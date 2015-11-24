
import logging

from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.controller.interfaces.button import ButtonControl
from fluxmonitor.code_executor.base import ST_RUNNING, ST_PAUSED
from fluxmonitor.services.base import ServiceBase
from fluxmonitor.err_codes import RESOURCE_BUSY

STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(ServiceBase):
    exclusive_component = None

    def __init__(self, options):
        ServiceBase.__init__(self, logger)
        self.local_control = LocalControl(self)

        try:
            self.button_control = ButtonControl(self, logger=logger)
        except Exception:
            logger.exception("Button control interface launch failed, ignore.")
            self.button_control = None

        try:
            if options.taskfile:
                sender = NullSender()
                cmd_task.select_file(options.taskfile, sender, raw=True)
                cmd_task.play(sender=sender)
            elif options.autoplay:
                sender = NullSender()
                if cmd_task.autoselect():
                    cmd_task.play(sender=sender)
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
        if message == "PLAYTOGL":
            if task_label == "PlayTask":
                st = self.this_task.get_status()["st_label"]
                if st in ("ABORTED", "COMPLETED"):
                    if not self.this_task.do_exit():
                        logger.error("Can not quit task")
                        return
                else:
                    logger.error("Can not quit task because busy")
                    return

            elif task_label != "CommandTask":
                logger.error("Can not start autoplay at %s", task_label)
                return

            sender = NullSender()
            if self.this_task.autoselect():
                self.this_task.play(sender=sender)

    def on_start(self):
        pass

    def on_shutdown(self):
        self.running = False
        self.local_control.close()
        self.local_control = None

        if self.button_control:
            self.button_control.close(self)
            self.button_control = None

    def is_exclusived(self):
        return True if self.exclusive_component else False

    def exclusive(self, component):
        if self.exclusive_component:
            raise RuntimeError(RESOURCE_BUSY)
        else:
            self.exclusive_component = component

    def release_exclusive(self, component):
        if self.exclusive_component == component:
            self.exclusive_component = None
        else:
            raise SystemError(DEVICE_ERROR, "COMPONENT_NOT_MATCH")

    def destory_exclusive(self):
        """Call this method from others to release exclusive lock"""
        if self.exclusive_component:
            self.exclusive_component.go_to_hell()
            self.exclusive_component = None
            return True
        else:
            return False


class NullSender(object):
    def send_text(self, *args):
        pass
