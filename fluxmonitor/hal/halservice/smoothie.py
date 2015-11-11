
from time import sleep
import logging

from serial import Serial

from fluxmonitor.misc.async_signal import AsyncIO
from .base import UartHalBase, BaseOnSerial

logger = logging.getLogger("hal.uart.smoothie")


class UartHal(UartHalBase, BaseOnSerial):
    hal_name = "manually"
    mb_port = hb_port = None
    mb = hb = None
    mb_io = hb_io = None

    def __init__(self, server):
        super(UartHal, self).__init__(server)
        self.mb_port, self.hb_port = server.options.mb, server.options.hb
        self._connect()
        server.add_read_event(self.mb_io)
        server.add_read_event(self.hb_io)

    def sendto_mainboard(self, buf):
        self.mb.write(buf)

    def sendto_headboard(self, buf):
        for c in buf:
            self.hb.write(c)
            sleep(0.005)

    def _connect(self):
        self.mb = Serial(port=self.mb_port, baudrate=115200, timeout=0)
        self.mb_io = AsyncIO(self.mb, self.on_recvfrom_mainboard)
        self.hb = Serial(port=self.hb_port, baudrate=115200, timeout=0)
        self.hb_io = AsyncIO(self.hb, self.on_recvfrom_headboard)

    def _disconnect(self):
        if self.mb:
            try:
                self.server.remove_read_event(self.mb_io)
                self.mb.close()
            except Exception:
                pass

            self.mb = None
            self.mb_io = None

        if self.hb:
            try:
                self.server.remove_read_event(self.hb_io)
                self.hb.close()
            except Exception:
                pass

            self.hb = None
            self.hb_io = None
