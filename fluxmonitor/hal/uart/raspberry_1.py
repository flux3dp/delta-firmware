
from time import sleep
import logging
import os

from serial import Serial
from RPi import GPIO

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.halprofile import MODEL_G1
from fluxmonitor.storage import Storage
from fluxmonitor.config import hal_config

from .base import UartHalBase, BaseOnSerial

L = logging.getLogger("hal.uart.rasp")

GPIO_HEAD_POW =  13
GPIO_USB_SERIAL = 15
GPIO_MAINBOARD = 16
HEAD_POWER_ON = GPIO.HIGH
HEAD_POWER_OFF = GPIO.LOW
USB_SERIAL_ON = GPIO.HIGH
USB_SERIAL_OFF = GPIO.LOW
MAINBOARD_ON = GPIO.HIGH
MAINBOARD_OFF = GPIO.LOW


class GPIOConteol(object):
    __usb_serial_gpio__ = USB_SERIAL_OFF
    head_enabled = True

    def init_gpio_control(self):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(GPIO_HEAD_POW, GPIO.OUT, initial=HEAD_POWER_ON)
        GPIO.setup(GPIO_MAINBOARD, GPIO.OUT, initial=MAINBOARD_ON)
        GPIO.setup(GPIO_USB_SERIAL, GPIO.OUT)
        L.debug("GPIO configured")

        self.update_ama0_routing()

    def __del__(self):
        L.debug("GPIO cleanup")
        GPIO.cleanup()

    def reset_mainboard(self):
        self.mainboard_disconnect()
        GPIO.output(GPIO_MAINBOARD, MAINBOARD_OFF)
        sleep(0.3)
        GPIO.output(GPIO_MAINBOARD, MAINBOARD_ON)
        sleep(1.5)
        self.mainboard_connect()

    def update_ama0_routing(self):
        if len(self.headboard_socks) > 0:
            if self.__usb_serial_gpio__ == USB_SERIAL_ON:
                L.debug("Headboard ON / USB OFF")
                self.head_enabled = True
                self.__usb_serial_gpio__ = USB_SERIAL_OFF
                GPIO.output(GPIO_USB_SERIAL, self.__usb_serial_gpio__)
        else:
            if self.__usb_serial_gpio__ == USB_SERIAL_OFF:
                L.debug("Headboard OFF / USB ON")
                self.head_enabled = False
                self.__usb_serial_gpio__ = USB_SERIAL_ON
                GPIO.output(GPIO_USB_SERIAL, self.__usb_serial_gpio__)

    def update_fw(self):
        L.debug("Update mainboard fireware")
        self.mainboard_disconnect()

        GPIO.output(GPIO_MAINBOARD, MAINBOARD_OFF)
        sleep(0.5)
        GPIO.output(GPIO_MAINBOARD, MAINBOARD_ON)
        sleep(1.0)

        storage = Storage("update_fw")
        tty = self.get_mainboard_port()
        L.debug("Mainboard at %s" % tty)

        try:
            if not storage.exists("mainboard.bin"):
                L.debug("mainboard.bin not found")
                return

            if os.system("stty -F %s 1200" % tty) != 0:
                L.debug("stty exec failed")
                return

            sleep(3.0)

            fw_path = storage.get_path("mainboard.bin")
            if os.system("bossac -p %s -e -w -v -b %s" % (
                         tty.split("/")[-1], fw_path)) != 0:
                L.debug("bossac exec failed")
                return

            os.rename(fw_path, fw_path + ".updated")

            GPIO.output(GPIO_MAINBOARD, MAINBOARD_OFF)
            sleep(0.5)
            GPIO.output(GPIO_MAINBOARD, MAINBOARD_ON)
            sleep(1.0)

            self.mainboard_connect()

        except Exception as e:
            L.exception("Error while update fireware")


class UartHal(UartHalBase, BaseOnSerial, GPIOConteol):
    mainboard_uart = raspi_uart = None
    mainboard_io = raspi_io = None

    hal_name = "raspberrypi-1"
    support_hal = [MODEL_G1, ]

    def __init__(self, server):
        super(UartHal, self).__init__(server)
        self.init_gpio_control()
        self._rasp_connect()
        self.mainboard_connect()

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
                sleep(0.005)

    def sendto_pc(self, buf):
        if not self.head_enabled:
            self.raspi_uart.write(buf)

    def reconnect(self):
        self.mainboard_disconnect()
        self.mainboard_connect()

    def get_mainboard_port(self):
        if os.path.exists("/dev/ttyACM0"):
            return "/dev/ttyACM0"
        elif os.path.exists("/dev/ttyACM1"):
            return "/dev/ttyACM1"
        else:
            raise Exception("Can not find mainboard device")

    def mainboard_connect(self):
        self.mainboard_uart = Serial(port=self.get_mainboard_port(),
                                     baudrate=115200, timeout=0)
        self.mainboard_io = AsyncIO(self.mainboard_uart,
                                    self.on_recvfrom_mainboard)
        self.server.add_read_event(self.mainboard_io)

    def mainboard_disconnect(self):
        if self.mainboard_uart:
            try:
                self.server.remove_read_event(self.mainboard_io)
                self.mainboard_uart.close()
                self.mainboard_uart = None
            except Exception:
                pass

    def _rasp_connect(self):
        self.raspi_uart = Serial(port="/dev/ttyAMA0",
                                 baudrate=115200, timeout=0)
        self.raspi_io = AsyncIO(self.raspi_uart,
                                self.on_recvfrom_raspi_io)
        self.server.add_read_event(self.raspi_io)

    def _rasp_disconnect(self):
        if self.raspi_uart:
            try:
                self.server.remove_read_event(self.raspi_io)
                self.raspi_uart.close()
                self.raspi_uart = None
            except Exception:
                pass

    def on_recvfrom_mainboard(self, sender):
        try:
            BaseOnSerial.on_recvfrom_mainboard(self, sender)
        except SerialException as e:
            self.reconnect()

    def on_connected_headboard(self, sender):
        UartHalBase.on_connected_headboard(self, sender)
        self.update_ama0_routing()

    def on_disconnect_headboard(self, ref):
        UartHalBase.on_disconnect_headboard(self, ref)
        self.update_ama0_routing()
