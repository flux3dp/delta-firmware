
from time import sleep
import logging

from serial import Serial

from fluxmonitor.misc.async_signal import AsyncIO
from .base import UartHalBase, BaseOnSerial

logger = logging.getLogger("hal.uart.smoothie")


class UartHal(UartHalBase, BaseOnSerial):
    hal_name = "smoothie"
    smoothie = None
    smoothie_io = None

    def __init__(self, server):
        super(UartHal, self).__init__(server)
        self.smoothie = Serial(port=server.options.serial_port,
                               baudrate=115200, timeout=0.05)
        self.smoothie_io = AsyncIO(self.smoothie,
                                   self.on_recvfrom_mainboard)

        server.add_read_event(self.smoothie_io)

    def sendto_mainboard(self, buf):
        self.smoothie.write(buf)

    def resetDTR(self):
        self.smoothie.setDTR(False)
        sleep(0.5)
        self.smoothie.setDTR(True)

    def reconnect(self):
        self._disconnect()
        self._connect()

    def _connect(self):
        self.smoothie = Serial(port=self.server.options.serial_port,
                               baudrate=115200, timeout=0.05)
        self.smoothie_io = AsyncIO(self.smoothie,
                                   self.on_recvfrom_mainboard)

        server.add_read_event(self.smoothie_io)

    def _disconnect(self):
        if self.smoothie:
            try:
                self.server.remove_read_event(self.smoothie_io)
                self.smoothie.close()
            except Exception:
                pass

            self.smoothie = None
            self.smoothie_io = None
