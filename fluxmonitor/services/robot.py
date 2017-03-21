
import weakref
import logging
import socket

from fluxmonitor.controller.tasks.play_manager import PlayerManager
from fluxmonitor.controller.tasks.play_manager import poweroff_led, clean_led
from fluxmonitor.controller.startup import device_startup
from fluxmonitor.interfaces.robot_internal import RobotUnixStreamInterface
from fluxmonitor.interfaces.hal_internal import HalControlClientHandler
from fluxmonitor.interfaces.usb2pc import USBHandler
from fluxmonitor.interfaces.robot import RobotSSLInterface, RobotCloudHandler
from fluxmonitor.interfaces.robot import RobotTcpInterface
from fluxmonitor.services.base import ServiceBase
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.err_codes import RESOURCE_BUSY, EXEC_OPERATION_ERROR
from fluxmonitor.storage import UserSpace, Storage, metadata
from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT

logger = logging.getLogger(__name__)


class Robot(ServiceBase):
    _hal_control = None
    _exclusive_component = None

    # This is a timestamp to recoard last exclusive quit at.
    # This data use to prevent autoplay when user double click at load/unload
    # filament.
    # First click: Terminate load/unload filament.
    # Then FLUX Studio send quit maintain in a short time.
    # Second click: Trigger autoplay <-- Prevent it occour
    _exclusive_release_at = 0

    def __init__(self, options):
        ServiceBase.__init__(self, logger, options)

        self.internl_interface = RobotUnixStreamInterface(self)

        if Storage("general", "meta")["bare"] == "Y":
            self.tcp_interface = RobotSSLInterface(self)
        else:
            self.tcp_interface = RobotTcpInterface(self)
        self._hal_reset_timer = self.loop.timer(5, 0, self._connect2hal)
        self._cloud_conn = set()

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

    def on_connect2usb(self, sock):
        logger.debug("Launch usb interface")
        self.usbhandler = USBHandler(self, "USB", sock)

    def on_connect2cloud(self, endpoint, token):
        def on_close(handler, *args):
            self._cloud_conn.remove(handler)

        c = RobotCloudHandler(self, endpoint, token, on_close)
        self._cloud_conn.add(c)

    def _connect2hal(self, watcher=None, revent=None):
        def close_callback(hal_control, error):
            self._hal_control = None
            if error:
                self._hal_reset_timer.set(5, 0)
                self._hal_reset_timer.start()

        try:
            h = HalControlClientHandler(
                self, on_button_event_callback=self.on_button_trigger,
                on_close_callback=close_callback)
            self._hal_control = h

        except Exception as e:
            # TODO: change logger level
            if isinstance(e, AssertionError):
                logger.error("HAL connecting error: %s", e.args[0])
            else:
                logger.error("HAL connecting error: %s", e)
            self._hal_control = None
            self._hal_reset_timer.set(5, 0)
            self._hal_reset_timer.start()

    def on_button_trigger(self, event, handler):
        logger.debug("Button trigger: %s", event)

        if self.exclusive_component:
            if isinstance(self.exclusive_component, PlayerManager):
                if event == "PLAYTOGL":
                    if self.exclusive_component.is_terminated:
                        self.exclusive_component.terminate()
                        self.exclusive_component = None
                        self.autoplay()
                elif event == "RUNTOGL":
                    if self.exclusive_component.is_paused:
                        self.exclusive_component.resume()
                    elif self.exclusive_component.is_running:
                        self.exclusive_component.pause()
                elif event == "ABORT":
                    if self.exclusive_component.is_terminated is False:
                        self.exclusive_component.abort()
                elif event == "POWER":
                    if self.exclusive_component.is_terminated:
                        self.exclusive_component.quit()
                        self.power_management()
            else:
                if event == "POWER":
                    self.destory_exclusive()
        else:
            # Not playing, autoplay
            if event == "PLAYTOGL":
                if time() - self._exclusive_release_at < 1:
                    logger.debug("Prevent autoplay")
                else:
                    self.autoplay()
            elif event == "POWER":
                self.power_management()

    def on_start(self):
        self._connect2hal()
        device_startup()

    def on_shutdown(self):
        self.running = False
        self.tcp_interface.close()
        self.tcp_interface = None
        self.internl_interface.close()
        self.internl_interface = None

        if self._hal_control:
            self._hal_control.close()
            self._hal_control = None
        if isinstance(self._exclusive_component, PlayerManager):
            self._exclusive_component.terminate()

    def power_management(self):
        if metadata.wifi_status & 1:
            # Power On
            logger.debug("Power On")
            metadata.wifi_status &= ~1
            clean_led()
        else:
            # Power Off
            logger.debug("Power Off")
            metadata.wifi_status |= 1
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
            self._exclusive_release_at = time()
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
