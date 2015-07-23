
from time import sleep
import logging

from serial import Serial
from RPi import GPIO

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.halprofile import MODEL_G1
from fluxmonitor.config import hal_config

from .base import UartHalBase, BaseOnSerial

L = logging.getLogger("hal.uart.rasp")

GPIO_USB_SERIAL = 15
USB_SERIAL_ON = GPIO.HIGH
USB_SERIAL_OFF = GPIO.LOW


class AMA0Routing(object):
    __gpio_val__ = USB_SERIAL_OFF
    head_enabled = True

    def init_ama0_routing(self):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(GPIO_USB_SERIAL, GPIO.OUT)
        L.debug("GPIO configured")

        self.update_ama0_routing()

    def __del__(self):
        L.debug("GPIO cleanup")
        GPIO.cleanup()

    def update_ama0_routing(self):
        if len(self.headboard_socks) > 0:
            if self.__gpio_val__ == USB_SERIAL_ON:
                L.debug("Headboard ON / USB OFF")
                self.head_enabled = True
                self.__gpio_val__ = USB_SERIAL_OFF
                GPIO.output(GPIO_USB_SERIAL, self.__gpio_val__)
        else:
            if self.__gpio_val__ == USB_SERIAL_OFF:
                L.debug("Headboard OFF / USB ON")
                self.head_enabled = False
                self.__gpio_val__ = USB_SERIAL_ON
                GPIO.output(GPIO_USB_SERIAL, self.__gpio_val__)


class UartHal(UartHalBase, BaseOnSerial, AMA0Routing):
    mainboard_uart = raspi_uart = None
    mainboard_io = raspi_io = None

    hal_name = "raspberrypi-1"
    support_hal = [MODEL_G1, ]

    def __init__(self, server):
        super(UartHal, self).__init__(server)
        self.init_ama0_routing()
        self._connect()

    def on_recvfrom_raspi_io(self, obj):
        if self.head_enabled:
            self.on_recvfrom_headboard(obj)
        else:
            self.on_recvfrom_pc(obj)

    def sendto_mainboard(self, buf):
        self.mainboard_uart.write(buf)

    def sendto_headboard(self, buf):
        if self.head_enabled:
            for c in buf:
                self.raspi_uart.write(c)
                sleep(0.02)

    def sendto_pc(self, buf):
        if not self.head_enabled:
            self.raspi_uart.write(buf)

    def reconnect(self):
        self._disconnect()
        self._connect()

    def _connect(self):
        self.mainboard_uart = Serial(port=hal_config["mainboard_uart"],
                                     baudrate=115200, timeout=0)

        self.raspi_uart = Serial(port="/dev/ttyAMA0",
                                 baudrate=115200, timeout=0)

        self.mainboard_io = AsyncIO(self.mainboard_uart,
                                    self.on_recvfrom_mainboard)
        self.raspi_io = AsyncIO(self.raspi_uart,
                                self.on_recvfrom_raspi_io)

        self.server.add_read_event(self.mainboard_io)
        self.server.add_read_event(self.raspi_io)

    def _disconnect(self):
        if self.mainboard_uart:
            try:
                self.server.remove_read_event(self.mainboard_io)
                self.mainboard_uart.close()
                self.mainboard_uart = None
            except Exception:
                pass

        if self.raspi_uart:
            try:
                self.server.remove_read_event(self.raspi_io)
                self.raspi_uart.close()
                self.raspi_uart = None
            except Exception:
                pass

    def on_connected_headboard(self, sender):
        UartHalBase.on_connected_headboard(self, sender)
        self.update_ama0_routing()

    def on_disconnect_headboard(self, ref):
        UartHalBase.on_disconnect_headboard(self, ref)
        self.update_ama0_routing()
