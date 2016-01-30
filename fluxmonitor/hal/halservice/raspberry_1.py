
from multiprocessing import Process
from time import time, sleep
from select import select
import logging
import struct
import os

from setproctitle import getproctitle, setproctitle
from serial import Serial, PARITY_EVEN, PARITY_NONE, SerialException
from RPi import GPIO
import pyev

from fluxmonitor.halprofile import MODEL_D1
from fluxmonitor.storage import Storage, CommonMetadata
from fluxmonitor.config import LENGTH_OF_LONG_PRESS_TIME as LLPT, \
    GAP_BETWEEN_DOUBLE_CLICK as GBDC, HEAD_POWER_TIMEOUT
from fluxmonitor.err_codes import NO_RESPONSE, UNKNOWN_ERROR, \
    SUBSYSTEM_ERROR, NOT_FOUND, NOT_SUPPORT
from .base import UartHalBase, BaseOnSerial

L = logging.getLogger("halservice.rasp")

GPIO_TOGGLE = (GPIO.LOW, GPIO.HIGH)


GPIO_HEAD_BOOT_MODE_PIN = 7
GPIO_FRONT_BUTTON_PIN = 12
GPIO_ALIVE_SIG_PIN = 3
GPIO_WIFI_ST_PIN = 5
GPIO_USB_SERIAL_PIN = 15
GPIO_HEAD_POW_PIN = 13
GPIO_MAINBOARD_POW_PIN = 16

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
    def __init__(self, loop, callback):
        GPIO.setup(12, GPIO.IN)

        self._rfd, self._wfd = os.pipe()
        self._proc = Process(target=self.serve_forever)
        self._proc.daemon = True
        self._proc.start()
        os.close(self._wfd)

        self._io_tigger = loop.io(self._rfd, pyev.EV_READ, self.on_trigger,
                                  callback)
        self._io_tigger.start()
        self._db_click_timer = loop.timer(GBDC, 0, self.on_trigger, callback)

    def fileno(self):
        return self._rfd

    def serve_forever(self):
        # Stand alone process entry
        try:
            setproctitle(getproctitle() + " (button monitor)")

            os.close(self._rfd)
            while True:
                long_press_sent = False

                GPIO.wait_for_edge(12, GPIO.FALLING)
                d = time()
                while GPIO.input(12) == 0:
                    sleep(0.002)

                    if not long_press_sent and time() - d > LLPT:
                        long_press_sent = True
                        os.write(self._wfd, '9')

                if long_press_sent:
                    continue
                else:
                    os.write(self._wfd, '1')

        finally:
            os.close(self._wfd)

    def on_trigger(self, watcher, revent):
        if revent == pyev.EV_READ:
            buf = os.read(self._rfd, 1)
            if buf:
                if buf == '1':
                    if self._db_click_timer.active:
                        self.send_db_click(watcher.data)
                        self._db_click_timer.stop()
                    else:
                        self._db_click_timer.set(GBDC, 0)
                        self._db_click_timer.start()
                elif buf == '9':
                    self.send_long_press(watcher.data)
            else:
                L.error("ButtonInterface is down")
                watcher.stop()

        elif revent == pyev.EV_TIMER:
            # CLICK
            self.send_click(watcher.data)

    def send_click(self, callback):
        logging.debug("Btn event: CLICK")

    def send_db_click(self, callback):
        logging.debug("Btn event: DBCLICK")
        callback('PLAYTOGL')
        callback('RUNTOGL ')

    def send_long_press(self, callback):
        logging.debug("Btn event: LONG_PRESS")
        callback('ABORT   ')

    def close(self):
        self._io_tigger.stop()
        self._io_tigger = None
        os.close(self._rfd)

        self._db_click_timer.stop()
        self._db_click_timer = None


class GPIOControl(object):
    _last_mainboard_sig = GPIO_TOGGLE[0]
    _usb_serial_stat = USB_SERIAL_OFF
    _head_power_stat = HEAD_POWER_OFF
    _head_power_timer = 0
    head_enabled = True

    def init_gpio_control(self):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(GPIO_HEAD_BOOT_MODE_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(GPIO_ALIVE_SIG_PIN, GPIO.OUT, initial=GPIO_TOGGLE[0])
        GPIO.setup(GPIO_WIFI_ST_PIN, GPIO.OUT, initial=GPIO_TOGGLE[0])

        for pin in GPIO_NOT_DEFINED:
            GPIO.setup(pin, GPIO.IN)

        GPIO.setup(GPIO_HEAD_POW_PIN, GPIO.OUT, initial=self._head_power_stat)
        GPIO.setup(GPIO_MAINBOARD_POW_PIN, GPIO.OUT, initial=MAINBOARD_ON)
        GPIO.setup(GPIO_USB_SERIAL_PIN, GPIO.OUT, initial=USB_SERIAL_OFF)
        L.debug("GPIO configured")

        self.update_ama0_routing()

    def proc_sig(self):
        _1 = self._last_mainboard_sig = (self._last_mainboard_sig + 1) % 2
        GPIO.output(GPIO_ALIVE_SIG_PIN, GPIO_TOGGLE[_1])

        wifi_flag = self.sm.wifi_status

        if wifi_flag & 64 > 0:
            GPIO.output(GPIO_WIFI_ST_PIN, GPIO.HIGH)
        else:
            GPIO.output(GPIO_WIFI_ST_PIN, GPIO_TOGGLE[_1])

        if not self.head_enabled and self._head_power_stat == HEAD_POWER_ON:
            if time() - self._head_power_timer > HEAD_POWER_TIMEOUT:
                L.debug("Head Power off")
                self._head_power_stat = HEAD_POWER_OFF
                GPIO.output(GPIO_HEAD_POW_PIN, HEAD_POWER_OFF)

    def __del__(self):
        L.debug("GPIO/PWM cleanup")
        GPIO.cleanup()

    def reset_mainboard(self, loop):
        self.mainboard_disconnect()
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_OFF)
        sleep(0.3)
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)
        sleep(1.5)
        self.mainboard_connect(loop)
        self._init_mainboard_status()

    def update_ama0_routing(self):
        if len(self.headboard_watchers) > 0:
            if self._usb_serial_stat == USB_SERIAL_ON:
                L.debug("Headboard ON / USB OFF")
                self.head_enabled = True
                self._usb_serial_stat = USB_SERIAL_OFF
                GPIO.output(GPIO_USB_SERIAL_PIN, self._usb_serial_stat)
        else:
            if self._usb_serial_stat == USB_SERIAL_OFF:
                L.debug("Headboard OFF / USB ON")
                self.head_enabled = False
                self._usb_serial_stat = USB_SERIAL_ON
                GPIO.output(GPIO_USB_SERIAL_PIN, self._usb_serial_stat)

        if self.head_enabled:
            if self._head_power_stat == HEAD_POWER_OFF:
                L.debug("Head Power on")
                GPIO.output(GPIO_HEAD_POW_PIN, HEAD_POWER_ON)
                self._head_power_stat = HEAD_POWER_ON
        else:
            if self._head_power_stat == HEAD_POWER_ON:
                L.debug("Head Power delay off")
                self._head_power_timer = time()

    def update_head_fw(self, stage_cb=lambda m: None):
        def wait_ack(stage):
            t = time()
            while time() - t < 5.0:
                rl = select((self.raspi_uart, ), (), (), 5.0)[0]
                if rl:
                    ret = self.raspi_uart.read(1)
                    if ret == 'y':
                        return
                    elif ret == '\x1f':
                        raise RuntimeError(SUBSYSTEM_ERROR, "HEAD RETURN 0x1f")
                    else:
                        raise RuntimeError(UNKNOWN_ERROR,
                                           "HEAD RETURN %s" % repr(ret))
            raise RuntimeError(NO_RESPONSE, stage)

        def send_cmd(cmd, stage):
            self.raspi_uart.write(chr(cmd))
            self.raspi_uart.write(chr(cmd ^ 0xFF))
            wait_ack(stage)
            sleep(0.1)

        def crc8(msg, init=0):
            crc = init
            for c in msg:
                crc = crc ^ ord(c)
            return chr(crc)

        def bootloader_hello():
            self.raspi_uart.write('\x7f')
            wait_ack("HELLO")

        L.debug("Update head fw")
        storage = Storage("update_fw")
        if not storage.exists("head.bin"):
            raise RuntimeError(NOT_FOUND)

        with storage.open("head.bin", "rb") as f:
            fw = f.read()

        size = len(fw)
        pages = size // 2048
        if size % 2048 > 0:
            pages += 1
        L.debug("Fw size=%i, use page=%i", size, pages)

        try:
            # Bootstrap
            stage_cb(b"B")

            self.raspi_uart.parity = PARITY_EVEN

            GPIO.output(GPIO_HEAD_POW_PIN, HEAD_POWER_OFF)
            GPIO.output(GPIO_HEAD_BOOT_MODE_PIN, GPIO.HIGH)
            sleep(0.5)

            GPIO.output(GPIO_HEAD_POW_PIN, HEAD_POWER_ON)
            sleep(0.5)

            self.raspi_uart.setRTS(0)
            self.raspi_uart.setDTR(0)
            sleep(0.1)
            self.raspi_uart.setDTR(1)
            sleep(0.5)

            # Hello
            stage_cb(b"H")

            try:
                bootloader_hello()
            except Exception:
                sleep(0.5)
                bootloader_hello()

            send_cmd(0x00, "G_VR")
            l = ord(self.raspi_uart.read())
            version = self.raspi_uart.read(1)
            a = self.raspi_uart.read(l)
            L.debug("VER %s", repr(a))
            wait_ack("G_VRL")
            L.debug("Update head: bootloader ver=%s", version)
            if version != '1':
                raise RuntimeError(NOT_SUPPORT)

            # Earse
            stage_cb(b"E")

            send_cmd(0x44, "G_ERASE")
            cmd = struct.pack(">H", pages - 1)
            cmd += "".join([struct.pack(">H", i) for i in xrange(pages)])
            self.raspi_uart.write(cmd)
            self.raspi_uart.write(crc8(cmd))
            wait_ack("G_E")

            # Write
            stage_cb(b"W")
            offset = 0
            while offset < size:
                stage_cb(("%08x" % (size - offset)).encode())
                l = min(size - offset, 128)
                send_cmd(0x31, "G_WINIT")
                addr = struct.pack(">I", 0x08000000 + offset)
                self.raspi_uart.write(addr)
                self.raspi_uart.write(crc8(addr))
                wait_ack("G_WREADY")
                payload = chr(l - 1) + fw[offset:offset + l]
                self.raspi_uart.write(payload)
                self.raspi_uart.write(crc8(payload))
                wait_ack("G_WDONE")
                offset += l

            stage_cb("00000000")
        finally:
            GPIO.output(GPIO_HEAD_BOOT_MODE_PIN, GPIO.LOW)
            GPIO.output(GPIO_HEAD_POW_PIN, HEAD_POWER_OFF)
            sleep(0.5)
            GPIO.output(GPIO_HEAD_POW_PIN, self._head_power_stat)
            self.raspi_uart.parity = PARITY_NONE

        L.debug("Update fw end")

    def update_fw(self, loop):
        L.debug("Update mainboard firemare")
        self.mainboard_disconnect()

        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_OFF)
        sleep(0.5)
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)
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

            GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_OFF)
            sleep(0.5)
            GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)
            sleep(1.0)

            self.mainboard_connect(loop)
            self._init_mainboard_status()

        except Exception:
            L.exception("Error while update firmware")


class UartHal(UartHalBase, BaseOnSerial, GPIOControl):
    mainboard_uart = raspi_uart = None
    mainboard_io = raspi_io = None

    hal_name = "raspberrypi-1"
    support_hal = [MODEL_D1, ]

    def __init__(self, kernel):
        super(UartHal, self).__init__(kernel)
        self.sm = CommonMetadata()

        self.init_gpio_control()

        self.btn_monitor = FrontButtonMonitor(kernel.loop,
                                              self.send_button_event)

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
        self.raspi_uart = Serial(port="/dev/ttyAMA0", baudrate=115200,
                                 stopbits=1, xonxoff=0, rtscts=0, timeout=0)
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
            w.data.send(event_buffer)
