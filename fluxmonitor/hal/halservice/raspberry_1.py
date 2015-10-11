
from multiprocessing import Process
from time import time, sleep
import logging
import os

from serial import Serial, SerialException
from RPi import GPIO

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.halprofile import MODEL_G1
from fluxmonitor.storage import Storage

from .base import UartHalBase, BaseOnSerial

L = logging.getLogger("halservice.rasp")

GPIO_TOGGLE = (GPIO.LOW, GPIO.HIGH)

GPIO_FRONT_BUTTON = 12
GPIO_MAINBOARD_SIG = 3
GPIO_ACTIVE_SIG = 5
GPIO_HEAD_POW = 13
GPIO_USB_SERIAL = 15
GPIO_MAINBOARD = 16
HEAD_POWER_ON = GPIO.HIGH
HEAD_POWER_OFF = GPIO.LOW
USB_SERIAL_ON = GPIO.HIGH
USB_SERIAL_OFF = GPIO.LOW
MAINBOARD_ON = GPIO.HIGH
MAINBOARD_OFF = GPIO.LOW
MAIN_BUTTON_DOWN = 0
MAIN_BUTTON_UP = 1


class FrontButtonMonitor(object):
    def __init__(self, trigger_list):
        GPIO.setup(12, GPIO.IN)

        self.trigger_list = trigger_list
        self._rfd, self._wfd = os.pipe()
        self._proc = Process(target=self.serve_forever)
        self._proc.daemon = True
        self.running = True
        self._proc.start()
        os.close(self._wfd)

    def fileno(self):
        return self._rfd

    def serve_forever(self):
        try:
            os.close(self._rfd)
            while self.running:
                abort_sent = False

                GPIO.wait_for_edge(12, GPIO.FALLING)
                d = time()
                while GPIO.input(12) == 0:
                    sleep(0.002)

                    if not abort_sent and time() - d > 3:
                        abort_sent = True
                        os.write(self._wfd, '9')
                        L.debug("Btn long press event triggered")

                if time() - d < 3:
                    os.write(self._wfd, '1')
                    L.debug("Btn press event triggered")
        finally:
            os.close(self._wfd)

    def on_read(self, kernel):
        buf = os.read(self._rfd, 1)
        if buf:
            if buf == '1':
                for sock in self.trigger_list:
                    sock.send('RUNTOGL ')  # RUN-TOGGLE
            elif buf == '9':
                for sock in self.trigger_list:
                    sock.send('ABORT   ')
        else:
            L.error("ButtonInterface is down")
            kernel.remove_read_event(self)

    def close(self):
        self.running = False
        os.close(self._rfd)


class GPIOConteol(object):
    _last_mainboard_sig = GPIO_TOGGLE[0]
    _last_active_sig = GPIO_TOGGLE[0]
    _last_sig_timestemp = 0
    __usb_serial_gpio__ = USB_SERIAL_OFF
    head_enabled = True

    def init_gpio_control(self):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(GPIO_MAINBOARD_SIG, GPIO.OUT, initial=GPIO_TOGGLE[0])
        GPIO.setup(GPIO_ACTIVE_SIG, GPIO.OUT, initial=GPIO_TOGGLE[0])

        GPIO.setup(GPIO_HEAD_POW, GPIO.OUT, initial=HEAD_POWER_ON)
        GPIO.setup(GPIO_MAINBOARD, GPIO.OUT, initial=MAINBOARD_ON)
        GPIO.setup(GPIO_USB_SERIAL, GPIO.OUT)
        L.debug("GPIO configured")

        self.update_ama0_routing()

    def proc_sig(self):
        if time() - self._last_sig_timestemp > 0.5:
            _1 = self._last_mainboard_sig = (self._last_mainboard_sig + 1) % 2
            _2 = self._last_active_sig = (self._last_active_sig + 1) % 2
            GPIO.output(GPIO_MAINBOARD_SIG, GPIO_TOGGLE[_1])
            GPIO.output(GPIO_ACTIVE_SIG, GPIO_TOGGLE[_2])
            self._last_sig_timestemp = time()

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
            self._init_mainboard_status()

        except Exception:
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
        self._init_mainboard_status()
        self.btn_monitor = FrontButtonMonitor(self.control_socks)

        server.add_loop_event(self)
        server.add_read_event(self.btn_monitor)

    def _init_mainboard_status(self):
        buf = self.storage.readall("on_boot")
        if buf:
            self.sendto_mainboard(buf)
        buf = self.storage.readall("adj")
        if buf:
            self.sendto_mainboard(buf)

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
        buf = self.storage.readall("on_connect")
        if buf:
            self.sendto_mainboard(buf)

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
        except SerialException:
            self.reconnect()

    def on_connected_headboard(self, sender):
        UartHalBase.on_connected_headboard(self, sender)
        self.update_ama0_routing()

    def on_disconnect_headboard(self, ref):
        UartHalBase.on_disconnect_headboard(self, ref)
        self.update_ama0_routing()

    def close(self):
        UartHalBase.close(self)
        self.btn_monitor.close()

    def on_loop(self, kernel):
        self.proc_sig()
