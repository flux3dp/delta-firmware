
from time import sleep
import logging

from serial import Serial

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.halprofile import MODEL_G1
from fluxmonitor.config import hal_config

from .base import UartHalBase, BaseOnSerial

logger = logging.getLogger("hal.uart.smoothie")


class UartHal(UartHalBase, BaseOnSerial):
    mainboard_uart = raspi_uart = None
    mainboard_io = raspi_io = None

    hal_name = "raspberrypi-1"
    support_hal = [MODEL_G1, ]

    def __init__(self, server):
        super(UartHal, self).__init__(server)
        self._connect()

    def on_recvfrom_raspi_io(self, obj):
        # TODO: NOT READY!
        if self.headboard_socks:
            self.on_recvfrom_headboard(obj)
        else:
            self.on_recvfrom_pc(obj)

    def sendto_mainboard(self, buf):
        self.mainboard_uart.write(buf)

    def sendto_headboard(self, buf):
        # TODO: NOT READY!
        for c in buf:
            self.raspi_uart.write(c)
            sleep(0.02)

    def sendto_pc(self, buf):
        # TODO: NOT READY!
        self.raspi_uart.write(buf)

    def reconnect(self):
        self._disconnect()
        self._connect()

    def _connect(self):
        self.mainboard_uart = Serial(port=hal_config["mainboard_uart"],
                                     baudrate=115200, timeout=0)
        # TODO: baudrate adjust to 28800
        self.raspi_uart = Serial(port=hal_config["headboard_uart"],
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
