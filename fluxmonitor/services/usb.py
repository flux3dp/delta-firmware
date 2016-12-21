
from multiprocessing.reduction import send_handle
from errno import ENOENT, ENOTSOCK
from select import select
from signal import SIGUSR2
from time import sleep
import logging
import socket

import msgpack

from fluxmonitor.interfaces.usb_config import UsbConfigInternalInterface
from fluxmonitor.interfaces.uart import UartHandler
from fluxmonitor.hal.usbcable import USBCable, attached_usb_devices
from fluxmonitor.config import ROBOT_ENDPOINT
from fluxmonitor import __version__ as VERSION  # noqa
from .base import ServiceBase

COMMON_ERRNO = (ENOENT, ENOTSOCK)
logger = logging.getLogger(__name__)


class UsbService(ServiceBase):
    uart = None
    usbcable = None
    dirty_status = False

    def __init__(self, options):
        super(UsbService, self).__init__(logger)
        self.timer_watcher = self.loop.timer(0, 30, self.on_timer)
        self.timer_watcher.start()

        self.internal_ifce = UsbConfigInternalInterface(self)

        self.udev_signal = self.loop.signal(SIGUSR2, self.udev_notify)
        self.udev_signal.start()

        if attached_usb_devices() > 0:
            self.udev_notify()

    def udev_notify(self, w=None, r=None):
        logger.debug("udev changed, launch usb daemon")
        if self.usbcable:
            logger.debug("close exist usb instance")
            self.usbcable.close()
            self.usbcable = None

        try:
            usbcable = USBCable()
            logger.debug("USB initialized")
        except SystemError as e:
            logger.error("USB initialize error: %s", e)
            self.dirty_status = True
            return

        payload = msgpack.packb((0x81, ))

        try:
            while True:
                s = socket.socket(socket.AF_UNIX)
                s.connect(ROBOT_ENDPOINT)
                s.send(payload)

                rl = select((s, ), (), (), 0.1)[0]
                if rl:
                    ret = s.recv(1)
                else:
                    logger.error("Error: robot endpoint resp usb init timeout")
                    s.close()
                    sleep(0.05)
                    continue

                if ret != b"F":
                    logger.error("Error: remote init return %s", repr(ret))
                    s.close()
                    sleep(0.05)
                    continue

                wl = select((), (s, ), (), 0.1)[1]
                if wl:
                    send_handle(s, usbcable.outside_sockfd, 0)
                else:
                    logger.error("Error: Can not write")
                    s.close()
                    sleep(0.05)
                    continue

                rl = select((s, ), (), (), 0.05)[0]
                if rl:
                    ret = s.recv(1)
                else:
                    logger.error("Error: robot endpoint resp usb fin timeout")
                    s.close()
                    sleep(0.05)

                if ret != b"X":
                    logger.error("Error remote complete return %s", repr(ret))
                    s.close()
                    continue

                usbcable.start()
                self.usbcable = usbcable
                s.close()
                self.dirty_status = False
                return

        except Exception:
            self.dirty_status = True
            logger.exception("Unknown error")

    def connect_uart(self):
        def connected(*args):
            logger.debug("Uart ready")

        def disconnected(*args):
            logger.debug("Uart disconnected")
            self.uart = None

        try:
            self.uart = UartHandler(self, on_connected_callback=connected,
                                    on_close_callback=disconnected)
            logger.info("Uart ready.")

        except IOError as e:
            if e.args[0] in COMMON_ERRNO:
                logger.debug("%s" % e)
            else:
                logger.exception("USB Connection error")

    def close_usb_serial(self, *args):
        if self.uart_watcher:
            self.uart_watcher.stop()
            self.uart_watcher = None

        if self.uart:
            self.uart.close()
            self.uart = None

    def on_start(self):
        pass

    def on_shutdown(self):
        self.internal_ifce.close()

    def on_timer(self, watcher, revent):
        try:
            if not self.uart:
                self.connect_uart()

            if self.dirty_status:
                if attached_usb_devices() > 0:
                    logger.error("Dirty flag marked and need start usb daemon")
                    self.udev_notify()
                else:
                    logger.error("Dirty flag marked but no usbcable connected")
                    self.dirty_status = False

            if self.usbcable and self.usbcable.is_alive() == 0:
                if attached_usb_devices():
                    logger.error("USB daemon dead but still attach cable. "
                                 "Restart usb")
                    self.udev_notify()
                else:
                    logger.debug("Clean usb daemon")
                    self.usbcable.close()
                    self.usbcable = None
        except Exception:
            logger.exception("Unknown error in timer")
