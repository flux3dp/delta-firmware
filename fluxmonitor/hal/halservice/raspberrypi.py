
from pkg_resources import resource_stream
from serial import Serial, SerialException  # PARITY_EVEN, PARITY_NONE,
from shutil import copyfileobj
from time import sleep
import logging
import pyev

# from fluxmonitor.misc.systime import systime as time
from fluxmonitor.halprofile import MODEL_D1
from fluxmonitor.storage import Metadata, Storage

from .raspberry_utils import (
    GPIOUtils,
    FrontButtonMonitor,
    PinMappingV0,
    PinMappingV1)
from .base import UartHalBase, BaseOnSerial

logger = logging.getLogger("halservice.rasp")


class UartHal(UartHalBase, BaseOnSerial):
    support_hal = [MODEL_D1, ]
    mainboard_uart = raspi_uart = None
    mainboard_io = raspi_io = None

    def __init__(self, kernel):
        super(UartHal, self).__init__(kernel)
        self.meta = Metadata()
        GPIOUtils.setup()

    def start(self):
        GPIOUtils.setup()
        hwprofile = GPIOUtils.get_hardware_profile()

        while hwprofile is None or "HARDWARE_VERSION" not in hwprofile:
            logger.error("Fetch hardware profile failed: %s", hwprofile)

            try:
                logger.error("Re-burn firmware")
                fsrc = resource_stream("fluxmonitor", "data/mainboard.bin")
                storage = Storage("update_fw")
                with storage.open("mainboard.bin", "wb") as fdst:
                    copyfileobj(fsrc, fdst)
                GPIOUtils.update_mbfw()
            except RuntimeWarning as e:
                logger.error("%s", e.args[0])
            except Exception:
                logger.exception("Re-burn firmware failed")

            sleep(3.0)
            hwprofile = GPIOUtils.get_hardware_profile()

        self.hwprofile = hwprofile
        if self.hwprofile["HARDWARE_VERSION"] == "1":
            self.gpio = PinMappingV1(self.meta)
        else:
            self.gpio = PinMappingV0(self.meta)

        self.btn_monitor = FrontButtonMonitor(self.gpio,
                                              self.kernel.loop,
                                              self.send_button_event)
        self.connect_uart()

    @property
    def hal_name(self):
        return "raspberrypi-%s" % self.gpio.version

    def on_recvfrom_raspi_io(self, watcher, revent):
        if self.gpio._head_enabled:
            self.on_recvfrom_headboard(watcher, revent)
        else:
            self.on_recvfrom_pc(watcher, revent)

    def sendto_mainboard(self, buf):
        self.mainboard_uart.write(buf)

    def sendto_headboard(self, buf):
        if self.gpio._head_enabled:
            for c in buf:
                self.raspi_uart.write(c)
                sleep(0.005)

    def sendto_pc(self, buf):
        if not self.gpio._head_enabled:
            self.raspi_uart.write(buf)

    def reconnect(self):
        self.disconnect_uart()
        self.connect_uart()

    def connect_uart(self):
        self.raspi_uart = Serial(port="/dev/ttyAMA0", baudrate=115200,
                                 stopbits=1, xonxoff=0, rtscts=0, timeout=0)

        self.raspi_io = self.kernel.loop.io(
            self.raspi_uart, pyev.EV_READ, self.on_recvfrom_raspi_io,
            self.raspi_uart)
        self.raspi_io.start()

        self.mainboard_uart = Serial(port=GPIOUtils.get_mainboard_port(),
                                     baudrate=115200, timeout=0)

        self.mainboard_io = self.kernel.loop.io(
            self.mainboard_uart, pyev.EV_READ, self.on_recvfrom_mainboard,
            self.mainboard_uart)
        self.mainboard_io.start()

    def disconnect_uart(self):
        if self.raspi_uart:
            try:
                self.raspi_io.stop()
                self.raspi_uart.close()
                self.raspi_uart = self.raspi_io = None
            except Exception:
                pass

        if self.mainboard_uart:
            try:
                self.mainboard_io.close()
                self.mainboard_uart.close()
                self.mainboard_uart = self.mainboard_io = None
            except Exception:
                pass

    def update_head_gpio(self):
        o = len(self.headboard_watchers) > 0
        self.gpio.update_toolhead_ctrl(o)

    def on_recvfrom_mainboard(self, watcher, revent):
        try:
            BaseOnSerial.on_recvfrom_mainboard(self, watcher, revent)
        except SerialException:
            self.reconnect()

    def on_connected_headboard(self, watcher, revent):
        UartHalBase.on_connected_headboard(self, watcher, revent)
        self.update_head_gpio()

    def on_disconnect_headboard(self, watcher):
        UartHalBase.on_disconnect_headboard(self, watcher)
        self.update_head_gpio()

    def close(self):
        UartHalBase.close(self)
        self.btn_monitor.close()
        GPIOUtils.teardown()

    def on_loop(self):
        self.gpio.on_timer()

    def reset_mainboard(self):
        self.disconnect_uart()
        sleep(0.3)
        GPIOUtils.reset_mainboard()
        sleep(0.3)
        # Ensure mainboard is back
        while True:
            try:
                GPIOUtils.get_mainboard_port()
                break
            except Exception:
                sleep(0.02)
        self.connect_uart()

    def reset_headboard(self):
        pass

    def update_fw(self):
        self.disconnect_uart()
        sleep(0.1)
        GPIOUtils.update_mbfw()
        sleep(0.2)
        self.connect_uart()

    def update_head_fw(self, cb):
        try:
            logger.debug("Begin update toolhead fw")
            self.disconnect_uart()
            sleep(0.1)
            self.gpio.update_hbfw(cb)
            logger.debug("Complete update toolhead fw")
        finally:
            self.connect_uart()

    def toolhead_on(self):
        if hasattr(self.gpio, "v24_power"):
            if self.gpio.v24_power is False:
                self.gpio.v24_power = True

    def toolhead_standby(self):
        if hasattr(self.gpio, "v24_power"):
            if self.gpio.v24_power is True:
                self.gpio.v24_power = False

    def send_button_event(self, event_buffer):
        self.kernel.on_button_event(event_buffer.rstrip())
