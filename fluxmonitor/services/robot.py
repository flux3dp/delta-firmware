
import weakref
import logging
import socket

from fluxmonitor.interfaces.robot import RobotTcpInterface
from fluxmonitor.controller.interfaces.button import ButtonControl
from fluxmonitor.controller.tasks.play_manager import PlayerManager
from fluxmonitor.controller.tasks.play_manager import poweroff_led, clean_led
from fluxmonitor.err_codes import RESOURCE_BUSY, EXEC_OPERATION_ERROR
from fluxmonitor.controller.startup import device_startup
from fluxmonitor.services.base import ServiceBase
from fluxmonitor.storage import UserSpace, Metadata, Storage
from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT


STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class Robot(ServiceBase):
    _exclusive_component = None

    def __init__(self, options):
        ServiceBase.__init__(self, logger, options)

        self.metadata = Metadata()
        self.local_control = RobotTcpInterface(self)
        self._connect_button_service()

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

    def _connect_button_service(self):
        try:
            self.button_control = ButtonControl(self, logger=logger)
        except Exception:
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.exception("Button control interface launch failed")
            else:
                logger.warn("Button control interface launch failed")
            self.button_control = None

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
                    if self.exclusive_component.is_terminated is False:
                        self.exclusive_component.abort()
                elif message == "POWER":
                    if self.exclusive_component.is_terminated:
                        self.exclusive_component.quit()
                        self.power_management()
            else:
                if message == "POWER":
                    self.destory_exclusive()
        else:
            # Not playing, autoplay
            if message == "PLAYTOGL":
                self.autoplay()
            elif message == "POWER":
                self.power_management()

    def on_start(self):
        device_startup()

    def on_shutdown(self):
        self.running = False
        self.local_control.close()
        self.local_control = None

        if self.button_control:
            self.button_control.close()
            self.button_control = None

    def power_management(self):
        if self.metadata.wifi_status & 1:
            # Power On
            logger.debug("Power On")
            self.metadata.wifi_status &= ~1
            clean_led()
        else:
            # Power Off
            logger.debug("Power Off")
            self.metadata.wifi_status |= 1
            poweroff_led()

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.connect(NETWORK_MANAGE_ENDPOINT)
            sock.send(b"power_change\x00")
            sock.close()
        except Exception:
            logger.exception("Flush network service status failed")

    def autoplay(self):
        storage = Storage("general", "meta")

        if storage["replay"] != "N":
            pathlist = (("USB", "autoplay.fc"), ("SD", "autoplay.fc",),
                        ("SD", "Recent/recent-1.fc",))
        else:
            pathlist = (("USB", "autoplay.fc"), ("SD", "autoplay.fc",))

        us = UserSpace()

        for candidate in pathlist:
            try:
                abspath = us.get_path(*candidate, require_file=True)
                logger.debug("Autoplay: %s", abspath)

                copyfile = (candidate[0] == "USB")
                pm = PlayerManager(self.loop, abspath, self.release_exclusive,
                                   copyfile=copyfile)
                self.exclusive(pm)
                return
            except RuntimeError:
                continue

        logger.debug("Autoplay failed")

    @property
    def exclusive_component(self):
        if self._exclusive_component:
            if isinstance(self._exclusive_component, PlayerManager):
                return self._exclusive_component
            else:
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
            raise RuntimeError(RESOURCE_BUSY,
                               self.exclusive_component.label)
        else:
            self.exclusive_component = component

    def release_exclusive(self, component):
        if self.exclusive_component == component:
            self.exclusive_component = None
        else:
            raise SystemError(EXEC_OPERATION_ERROR, "COMPONENT_NOT_MATCH")

    def destory_exclusive(self):
        """Call this method from others to release exclusive lock"""
        if self.exclusive_component:
            if isinstance(self.exclusive_component, PlayerManager):
                raise RuntimeError(RESOURCE_BUSY)
            else:
                try:
                    self.exclusive_component.on_dead("Kicked")
                except Exception:
                    logger.exception("Unknow Error")
                self.exclusive_component = None
                return True
        else:
            return False
