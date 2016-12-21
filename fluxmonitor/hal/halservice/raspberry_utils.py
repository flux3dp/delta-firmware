
from multiprocessing import Process
from select import select
from serial import Serial, PARITY_EVEN, PARITY_NONE
from time import sleep
from RPi import GPIO
import logging
import struct
import pyev
import os

from setproctitle import getproctitle, setproctitle
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.err_codes import NO_RESPONSE, UNKNOWN_ERROR, \
    SUBSYSTEM_ERROR, NOT_FOUND, NOT_SUPPORT
from fluxmonitor.storage import Storage
from fluxmonitor.config import (
    LENGTH_OF_LONG_PRESS_TIME as LLPT,
    GAP_BETWEEN_DOUBLE_CLICK as GBDC,
    HEAD_POWER_TIMEOUT)

logger = logging.getLogger("halservice.rasp")


GPIO_TOGGLE = (GPIO.LOW, GPIO.HIGH)
GPIO_MAINBOARD_POW_PIN = 16
MAINBOARD_ON = GPIO.HIGH
MAINBOARD_OFF = GPIO.LOW


class GPIOUtils(object):
    @classmethod
    def get_mainboard_port(cls):
        if os.path.exists("/dev/ttyACM0"):
            return "/dev/ttyACM0"
        elif os.path.exists("/dev/ttyACM1"):
            return "/dev/ttyACM1"
        elif os.path.exists("/dev/ttyACM2"):
            return "/dev/ttyACM2"
        else:
            raise Exception("Can not find mainboard device")

    @classmethod
    def setup(cls):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(GPIO_MAINBOARD_POW_PIN, GPIO.OUT, initial=MAINBOARD_ON)

    @classmethod
    def teardown(cls):
        logger.debug("Teardown GPIO, reset mainboard")
        cls.reset_mainboard()
        GPIO.cleanup()

    @classmethod
    def get_hardware_profile(cls):
        serial = Serial(port=cls.get_mainboard_port(), baudrate=115200,
                        timeout=0.075)
        serial.write("M115\n")
        buf = serial.readall()
        serial.close()
        for ln in buf.split("\n"):
            if ln.startswith(b"DATA "):
                s = ln[5:].strip()
                return dict(":" in p and p.split(":", 2) or (p, None)
                            for p in s.split(" "))

    @classmethod
    def reset_mainboard(cls):
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_OFF)
        sleep(0.5)
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)

    @classmethod
    def update_mbfw(cls):
        cls.reset_mainboard()
        sleep(1.0)

        storage = Storage("update_fw")
        tty = cls.get_mainboard_port()

        if not storage.exists("mainboard.bin"):
            raise RuntimeWarning("mainboard.bin not found")

        if os.system("stty -F %s 1200" % tty) != 0:
            raise RuntimeWarning("stty exec failed")

        sleep(2.0)

        fw_path = storage.get_path("mainboard.bin")
        if os.system("bossac -p %s -e -w -v -b %s" % (
                     tty.split("/")[-1], fw_path)) != 0:
            raise RuntimeWarning("bossac exec failed")

        os.rename(fw_path, fw_path + ".updated")
        os.system("sync")
        sleep(0.75)
        cls.reset_mainboard()
        sleep(0.75)

    @classmethod
    def close(cls):
        pass


class PinMappingShared(object):
    PIN_NOT_DEFINED = (22, 24, )
    TOOLHEAD_POWER = 13
    TOOLHEAD_BOOT = 7
    FRONT_BUTTON = 12
    RIO_1 = 3
    RIO_2 = 5
    MIO_1 = 22

    TOOLHEAD_POWER_ON = GPIO.HIGH
    TOOLHEAD_POWER_OFF = GPIO.LOW
    TOOLHEAD_BOOT_ON = GPIO.HIGH
    TOOLHEAD_BOOT_OFF = GPIO.LOW

    _last_mainboard_sig = GPIO.LOW
    _head_enabled = False
    _head_power_stat = TOOLHEAD_POWER_ON
    _head_power_timer = 0

    def __init__(self, metadata):
        self.meta = metadata
        GPIO.setup(self.TOOLHEAD_BOOT, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.TOOLHEAD_POWER, GPIO.OUT,
                   initial=self._head_power_stat)
        GPIO.setup(self.MIO_1, GPIO.IN)
        GPIO.setup(self.RIO_1, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.RIO_2, GPIO.OUT, initial=GPIO.LOW)

        for pin in self.PIN_NOT_DEFINED:
            GPIO.setup(pin, GPIO.IN)

        self._head_power_timer = time()
        self.on_timer()

    @property
    def mio_1(self):
        return GPIO.input(self.MIO_1)

    def set_toolhead_boot(self, o):
        mode = self.TOOLHEAD_BOOT_ON if o else self.TOOLHEAD_BOOT_OFF
        GPIO.output(self.TOOLHEAD_BOOT, mode)

    @property
    def toolhead_power(self):
        return self._head_power_stat == self.TOOLHEAD_POWER_ON

    @toolhead_power.setter
    def toolhead_power(self, val):
        if val:
            if self._head_power_stat != self.TOOLHEAD_POWER_ON:
                self._head_power_stat = self.TOOLHEAD_POWER_ON
                GPIO.output(self.TOOLHEAD_POWER, self.TOOLHEAD_POWER_ON)
                logger.debug("Head Power On")
        else:
            if self._head_power_stat != self.TOOLHEAD_POWER_OFF:
                self._head_power_stat = self.TOOLHEAD_POWER_OFF
                GPIO.output(self.TOOLHEAD_POWER, self.TOOLHEAD_POWER_OFF)
                logger.debug("Head Power Off")

    def update_hbfw(self, stage_cb=lambda m: None):
        raspi_uart = Serial(port="/dev/ttyAMA0", baudrate=115200,
                            stopbits=1, xonxoff=0, rtscts=0, timeout=0)

        def wait_ack(stage):
            t = time()
            while time() - t < 5.0:
                rl = select((raspi_uart, ), (), (), 5.0)[0]
                if rl:
                    ret = raspi_uart.read(1)
                    if ret == 'y':
                        return
                    elif ret == '\x1f':
                        raise RuntimeError(SUBSYSTEM_ERROR, "HEAD RETURN 0x1f")
                    else:
                        raise RuntimeError(UNKNOWN_ERROR,
                                           "HEAD RETURN %s" % repr(ret))
            raise RuntimeError(NO_RESPONSE, stage)

        def send_cmd(cmd, stage):
            raspi_uart.write(chr(cmd))
            raspi_uart.write(chr(cmd ^ 0xFF))
            wait_ack(stage)
            sleep(0.1)

        def crc8(msg, init=0):
            crc = init
            for c in msg:
                crc = crc ^ ord(c)
            return chr(crc)

        def bootloader_hello():
            raspi_uart.write('\x7f')
            wait_ack("HELLO")

        logger.debug("Update head fw")
        storage = Storage("update_fw")
        if not storage.exists("head.bin"):
            raise RuntimeError(NOT_FOUND)

        with storage.open("head.bin", "rb") as f:
            fw = f.read()

        size = len(fw)
        pages = size // 2048
        if size % 2048 > 0:
            pages += 1
        logger.debug("Fw size=%i, use page=%i", size, pages)

        try:
            # Bootstrap
            stage_cb(b"B")

            raspi_uart.parity = PARITY_EVEN

            GPIO.output(self.TOOLHEAD_POWER, self.TOOLHEAD_POWER_OFF)
            GPIO.output(self.TOOLHEAD_BOOT, GPIO.HIGH)
            sleep(0.5)

            GPIO.output(self.TOOLHEAD_POWER, self.TOOLHEAD_POWER_ON)
            sleep(0.5)

            raspi_uart.setRTS(0)
            raspi_uart.setDTR(0)
            sleep(0.1)
            raspi_uart.setDTR(1)
            sleep(0.5)

            # Hello
            stage_cb(b"H")

            try:
                bootloader_hello()
            except Exception:
                sleep(0.5)
                bootloader_hello()

            send_cmd(0x00, "G_VR")
            l = ord(raspi_uart.read())
            version = raspi_uart.read(1)
            a = raspi_uart.read(l)
            logger.debug("VER %s", repr(a))
            wait_ack("G_VRL")
            logger.debug("Update head: bootloader ver=%s", version)
            if version != '1':
                raise RuntimeError(NOT_SUPPORT)

            # Earse
            stage_cb(b"E")

            send_cmd(0x44, "G_ERASE")
            cmd = struct.pack(">H", pages - 1)
            cmd += "".join([struct.pack(">H", i) for i in xrange(pages)])
            raspi_uart.write(cmd)
            raspi_uart.write(crc8(cmd))
            wait_ack("G_E")

            # Write
            stage_cb(b"W")
            offset = 0
            while offset < size:
                stage_cb(("%07x" % (size - offset)).encode())
                l = min(size - offset, 128)
                send_cmd(0x31, "G_WINIT")
                addr = struct.pack(">I", 0x08000000 + offset)
                raspi_uart.write(addr)
                raspi_uart.write(crc8(addr))
                wait_ack("G_WREADY")
                payload = chr(l - 1) + fw[offset:offset + l]
                raspi_uart.write(payload)
                raspi_uart.write(crc8(payload))
                wait_ack("G_WDONE")
                offset += l

            stage_cb("00000000")
        finally:
            GPIO.output(self.TOOLHEAD_BOOT, GPIO.LOW)
            GPIO.output(self.TOOLHEAD_POWER, self.TOOLHEAD_POWER_OFF)
            sleep(0.5)
            GPIO.output(self.TOOLHEAD_POWER, self._head_power_stat)
            raspi_uart.parity = PARITY_NONE
            raspi_uart.close()

        logger.debug("Update fw end")

    def on_timer(self):
        _1 = self._last_mainboard_sig = (self._last_mainboard_sig + 1) % 2

        wifi_flag = self.meta.wifi_status

        if wifi_flag & 32 > 0:
            # Hostapd Mode
            GPIO.output(self.RIO_1, GPIO.HIGH)
            GPIO.output(self.RIO_2, GPIO_TOGGLE[_1])
        else:
            # wpa supplicant
            GPIO.output(self.RIO_1, GPIO_TOGGLE[_1])
            if wifi_flag & 64 > 0:
                GPIO.output(self.RIO_2, GPIO.HIGH)
            else:
                GPIO.output(self.RIO_2, GPIO_TOGGLE[_1])

        if self._head_enabled is False and self.toolhead_power is True:
            if time() - self._head_power_timer > HEAD_POWER_TIMEOUT:
                self.toolhead_power = False

    def close(self):
        GPIO.output(self.RIO_1, GPIO.LOW)
        GPIO.output(self.RIO_2, GPIO.LOW)


class PinMappingV0(PinMappingShared):
    version = 0

    USB_SERIAL = 15
    USB_SERIAL_ON = GPIO.HIGH
    USB_SERIAL_OFF = GPIO.LOW

    _usb_serial_stat = USB_SERIAL_ON

    def __init__(self, metadata):
        super(PinMappingV0, self).__init__(metadata)
        GPIO.setup(self.USB_SERIAL, GPIO.OUT,
                   initial=self._usb_serial_stat)

    @property
    def usb_serial_power(self):
        return self._usb_serial_stat == self.USB_SERIAL_ON

    @usb_serial_power.setter
    def usb_serial_power(self, val):
        if val:
            if self._usb_serial_stat != self.USB_SERIAL_ON:
                self._usb_serial_stat = self.USB_SERIAL_ON
                GPIO.output(self.USB_SERIAL, self.USB_SERIAL_ON)
                logger.debug("USB Serial On")
        else:
            if self._usb_serial_stat != self.USB_SERIAL_OFF:
                self._usb_serial_stat = self.USB_SERIAL_OFF
                GPIO.output(self.USB_SERIAL, self.USB_SERIAL_OFF)
                logger.debug("USB Serial Off")

    def update_toolhead_ctrl(self, toolhead_operating):
        if toolhead_operating:
            if self.usb_serial_power is True:
                logger.debug("Headboard ON / USB OFF")
                self.usb_serial_power = False
                self._head_enabled = True
        else:
            if self.usb_serial_power is False:
                logger.debug("Headboard OFF / USB ON")
                self.usb_serial_power = True
                self._head_enabled = False

        if self._head_enabled:
            if self.toolhead_power is False:
                self.toolhead_power = True
        else:
            if self.toolhead_power is True:
                logger.debug("Head Power delay turn off")
                self._head_power_timer = time()


class PinMappingV1(PinMappingShared):
    version = 1

    V24_POWER = 15
    V24_POWER_ON = GPIO.HIGH
    V24_POWER_OFF = GPIO.LOW

    _v24_stat = V24_POWER_OFF

    def __init__(self, metadata):
        super(PinMappingV1, self).__init__(metadata)
        GPIO.setup(self.V24_POWER, GPIO.OUT, initial=self.V24_POWER_OFF)

    @property
    def v24_power(self):
        return self._v24_stat == self.V24_POWER_ON

    @v24_power.setter
    def v24_power(self, val):
        if val:
            if self._v24_stat != self.V24_POWER_ON:
                self._v24_stat = self.V24_POWER_ON
                GPIO.output(self.V24_POWER, self.V24_POWER_ON)
                logger.debug("24v On")
        else:
            if self._v24_stat != self.V24_POWER_OFF:
                self._v24_stat = self.V24_POWER_OFF
                GPIO.output(self.V24_POWER, self.V24_POWER_OFF)
                logger.debug("24v Off")

    def update_toolhead_ctrl(self, toolhead_operating):
        if toolhead_operating:
            if self._head_enabled is False:
                self._head_enabled = self.toolhead_power = True
        else:
            if self.v24_power is True:
                self.v24_power = False

            if self._head_enabled is True:
                self._head_enabled = False
                logger.debug("Head Power delay off")
                self._head_power_timer = time()


class FrontButtonMonitor(object):
    def __init__(self, pin_mapping, loop, callback):
        GPIO.setup(pin_mapping.FRONT_BUTTON, GPIO.IN)

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

        except RuntimeError:
            pass
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
                logger.warning("ButtonInterface is down")
                watcher.stop()

        elif revent == pyev.EV_TIMER:
            # CLICK
            self.send_click(watcher.data)

    def send_click(self, callback):
        logger.debug("Btn event: CLICK")

    def send_db_click(self, callback):
        logger.debug("Btn event: DBCLICK")
        callback('PLAYTOGL')
        callback('RUNTOGL ')

    def send_long_press(self, callback):
        logger.debug("Btn event: LONG_PRESS")
        callback('POWER   ')
        callback('ABORT   ')

    def close(self):
        self._io_tigger.stop()
        self._io_tigger = None
        os.close(self._rfd)

        self._db_click_timer.stop()
        self._db_click_timer = None
