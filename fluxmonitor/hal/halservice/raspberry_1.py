
from multiprocessing import Process
from time import time, sleep
import logging
import os

from setproctitle import getproctitle, setproctitle
from serial import Serial, SerialException
from RPi import GPIO
import pyev

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.halprofile import MODEL_G1
from fluxmonitor.storage import Storage, CommonMetadata

from .base import UartHalBase, BaseOnSerial

L = logging.getLogger("halservice.rasp")

GPIO_TOGGLE = (GPIO.LOW, GPIO.HIGH)


GPIO_HEAD_BOOT_MODE = 7
GPIO_FRONT_BUTTON = 12
GPIO_MAINBOARD_SIG = 3
GPIO_ACTIVE_SIG = 5
GPIO_HEAD_POW = 13
GPIO_USB_SERIAL = 15
GPIO_MAINBOARD = 16

GPIO_NOT_DEFINED = (22, 24, )

HEAD_POWER_ON = GPIO.HIGH
HEAD_POWER_OFF = GPIO.LOW
USB_SERIAL_ON = GPIO.HIGH
USB_SERIAL_OFF = GPIO.LOW
MAINBOARD_ON = GPIO.HIGH
MAINBOARD_OFF = GPIO.LOW
MAIN_BUTTON_DOWN = 0
MAIN_BUTTON_UP = 1


class FrontButtonMonitor(object):
    def __init__(self):
        GPIO.setup(12, GPIO.IN)

        self.running = True
        self._rfd, self._wfd = os.pipe()
        self._proc = Process(target=self.serve_forever)
        self._proc.daemon = True
        self._proc.start()
        os.close(self._wfd)

    def fileno(self):
        return self._rfd

    def serve_forever(self):
        try:
            setproctitle(getproctitle() + " (button monitor)")

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

    def on_trigger(self, watcher, revent):
        buf = os.read(self._rfd, 1)
        if buf:
            if buf == '1':
                watcher.data('RUNTOGL ')
            elif buf == '9':
                watcher.data('ABORT   ')
        else:
            L.error("ButtonInterface is down")
            kernel.remove_read_event(self)

    def close(self):
        self.running = False
        os.close(self._rfd)


class GPIOConteol(object):
    _last_mainboard_sig = GPIO_TOGGLE[0]
    _last_sig_timestemp = 0
    _last_active_st = -1
    __usb_serial_gpio__ = USB_SERIAL_OFF
    head_enabled = True

    def init_gpio_control(self):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(GPIO_HEAD_BOOT_MODE, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(GPIO_MAINBOARD_SIG, GPIO.OUT, initial=GPIO_TOGGLE[0])
        GPIO.setup(GPIO_ACTIVE_SIG, GPIO.OUT)
        self._active_sig_pwm = GPIO.PWM(GPIO_ACTIVE_SIG, 1.0)
        self._active_sig_pwm.start(50)

        for pin in GPIO_NOT_DEFINED:
            GPIO.setup(pin, GPIO.IN)

        GPIO.setup(GPIO_HEAD_POW, GPIO.OUT, initial=HEAD_POWER_ON)
        GPIO.setup(GPIO_MAINBOARD, GPIO.OUT, initial=MAINBOARD_ON)
        GPIO.setup(GPIO_USB_SERIAL, GPIO.OUT)
        L.debug("GPIO configured")

        self.update_ama0_routing()

    def proc_sig(self):
        if time() - self._last_sig_timestemp > 0.5:
            _1 = self._last_mainboard_sig = (self._last_mainboard_sig + 1) % 2
            GPIO.output(GPIO_MAINBOARD_SIG, GPIO_TOGGLE[_1])

            st = self.sm.wifi_status
            if st != self._last_active_st:
                self._last_active_st = st
                self._active_sig_pwm.stop()

                wifi_st = self.sm.wifi_status
                if wifi_st & 128:
                    self._active_sig_pwm.start(0)
                elif wifi_st & 64:
                    self._active_sig_pwm.start(100)
                else:
                    self._active_sig_pwm.start(50)

            self._last_sig_timestemp = time()

    def __del__(self):
        L.debug("GPIO/PWM cleanup")
        GPIO.cleanup()

    def reset_mainboard(self, watcher):
        self.mainboard_disconnect()
        GPIO.output(GPIO_MAINBOARD, MAINBOARD_OFF)
        sleep(0.3)
        GPIO.output(GPIO_MAINBOARD, MAINBOARD_ON)
        sleep(1.5)
        self.mainboard_connect(watcher.loop)

    def update_ama0_routing(self):
        if len(self.headboard_watchers) > 0:
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

    def update_fw(self, watcher):
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

            self.mainboard_connect(watcher.loop)
            self._init_mainboard_status()

        except Exception:
            L.exception("Error while update fireware")


class UartHal(UartHalBase, BaseOnSerial, GPIOConteol):
    mainboard_uart = raspi_uart = None
    mainboard_io = raspi_io = None

    hal_name = "raspberrypi-1"
    support_hal = [MODEL_G1, ]

    def __init__(self, kernel):
        super(UartHal, self).__init__(kernel)
        self.sm = CommonMetadata()

        self.init_gpio_control()

        self.btn_monitor = FrontButtonMonitor()
        self.btn_watcher = kernel.loop.io(self.btn_monitor, pyev.EV_READ,
                                          self.btn_monitor.on_trigger,
                                          self.send_button_event)
        self.btn_watcher.start()

        self._rasp_connect(kernel.loop)
        self.mainboard_connect(kernel.loop)
        self._init_mainboard_status()

        self.loop_watcher = kernel.loop.timer(5, 5, self.on_loop)
        self.loop_watcher.start()

    def _init_mainboard_status(self):
        corr_str = "M666 X%(X).4f Y%(Y).4f Z%(Z).4f H%(H).4f\n" % \
                   self.sm.plate_correction
        L.debug("Init with corr: %s", corr_str)

        self.sendto_mainboard(corr_str)
        self.sendto_mainboard("G28\n")
        buf = self.storage.readall("on_boot")
        if buf:
            self.sendto_mainboard(buf)

    def on_recvfrom_raspi_io(self, watcher, revent):
        if self.head_enabled:
            self.on_recvfrom_headboard(watcher, revent)
        else:
            self.on_recvfrom_pc(watcher, revent)

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

    def reconnect(self, loop):
        self.mainboard_disconnect()
        self.mainboard_connect(loop)
        buf = self.storage.readall("on_connect")
        if buf:
            self.sendto_mainboard(buf)

    def get_mainboard_port(self):
        if os.path.exists("/dev/ttyACM0"):
            return "/dev/ttyACM0"
        elif os.path.exists("/dev/ttyACM1"):
            return "/dev/ttyACM1"
        elif os.path.exists("/dev/ttyACM2"):
            return "/dev/ttyACM2"
        else:
            raise Exception("Can not find mainboard device")

    def mainboard_connect(self, loop):
        self.mainboard_uart = Serial(port=self.get_mainboard_port(),
                                     baudrate=115200, timeout=0)

        self.mainboard_io = loop.io(self.mainboard_uart, pyev.EV_READ,
                                    self.on_recvfrom_mainboard,
                                    self.mainboard_uart)
        self.mainboard_io.start()

    def mainboard_disconnect(self):
        if self.mainboard_uart:
            try:
                self.mainboard_io.close()
                self.mainboard_uart.close()
                self.mainboard_uart = self.mainboard_io = None
            except Exception:
                pass

    def _rasp_connect(self, loop):
        self.raspi_uart = Serial(port="/dev/ttyAMA0",
                                 baudrate=115200, timeout=0)
        self.raspi_io = loop.io(self.raspi_uart, pyev.EV_READ,
                                self.on_recvfrom_raspi_io,
                                self.raspi_uart)
        self.raspi_io.start()

    def _rasp_disconnect(self):
        if self.raspi_uart:
            try:
                self.raspi_io.stop()
                self.raspi_uart.close()
                self.raspi_uart = self.raspi_io = None
            except Exception:
                pass

    def on_recvfrom_mainboard(self, watcher, revent):
        try:
            BaseOnSerial.on_recvfrom_mainboard(self, watcher, revent)
        except SerialException:
            self.reconnect(watcher.loop)

    def on_connected_headboard(self, watcher, revent):
        UartHalBase.on_connected_headboard(self, watcher, revent)
        self.update_ama0_routing()

    def on_disconnect_headboard(self, watcher):
        UartHalBase.on_disconnect_headboard(self, watcher)
        self.update_ama0_routing()

    def close(self):
        UartHalBase.close(self)
        self.btn_monitor.close()
        self.loop_watcher.stop()

    def on_loop(self, watcher, revent):
        self.proc_sig()

    def send_button_event(self, event_buffer):
        for w in self.control_watchers:
            w.data.sendt(event_buffer)
