
import weakref
import logging

from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.controller.interfaces.button import ButtonControl
from fluxmonitor.controller.tasks.play_manager import PlayerManager
from fluxmonitor.services.base import ServiceBase
from fluxmonitor.err_codes import RESOURCE_BUSY, DEVICE_ERROR
from fluxmonitor.storage import UserSpace


STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(ServiceBase):
    _exclusive_component = None

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
                logger.debug("Autoplay: %s", options.taskfile)
                pm = PlayerManager(self.loop, options.taskfile,
                                   self.release_exclusive)
                self.exclusive(pm)
            elif options.autoplay:
                self.autoplay()
        except Exception:
            logger.exception("Error while setting task at init")

    def on_button_control(self, message):
        logger.debug("Button trigger: %s", message)

        if self.exclusive_component:
            if isinstance(self.exclusive_component, PlayerManager):
                if message == "PLAYTOGL":
                    if self.exclusive_component.is_terminated:
                        self.exclusive_component.terminate()
                        self.exclusive_component = None
                        self.autoplay()
                elif message == "RUNTOGL":
                    if self.exclusive_component.is_paused:
                        self.exclusive_component.resume()
                    elif self.exclusive_component.is_running:
                        self.exclusive_component.pause()
                elif message == "ABORT":
                    self.exclusive_component.abort()
            else:
                logger.debug("Button trigger failed: Resource busy")
        else:
            # Not playing, autoplay
            if message == "PLAYTOGL":
                self.autoplay()

    def on_start(self):
        pass

    def on_shutdown(self):
        self.running = False
        self.local_control.close()
        self.local_control = None

        if self.button_control:
            self.button_control.close()
            self.button_control = None

    def autoplay(self):
        pathlist = (("USB", "autoplay.fc"), ("SD", "autoplay.fc",))
        us = UserSpace()

        for candidate in pathlist:
            try:
                abspath = us.get_path(*candidate, require_file=True)
                logger.debug("Autoplay: %s", abspath)
                pm = PlayerManager(self.loop, abspath, self.release_exclusive)
                self.exclusive(pm)
                return
            except RuntimeError:
                continue

        logger.debug("Autoplay failed")

    @property
    def exclusive_component(self):
        if self._exclusive_component:
            return self._exclusive_component()
        else:
            return None

    @exclusive_component.setter
    def exclusive_component(self, val):
        if isinstance(val, PlayerManager):
            self._exclusive_component = val
        elif val is None:
            self._exclusive_component = None
        else:
            self._exclusive_component = weakref.ref(val)

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
