
from serial import Serial

from fluxmonitor.misc.async_signal import AsyncIO
from .base import UartHalBase, BaseOnSerial


class UartHal(UartHalBase, BaseOnSerial):
    hal_name = "smoothie"

    def __init__(self, server):
        super(UartHal, self).__init__(server)
        self.smoothie = Serial(port=server.options.serial_port,
                               baudrate=115200, timeout=0.05)
        self.smoothie_io = AsyncIO(self.smoothie,
                                   self.on_recvfrom_mainboard)

        server.add_read_event(self.smoothie_io)

    def on_recv_smoothie(self, buf):
        buf = self.smoothie.readall()

    def sendto_mainboard(self, buf):
        self.smoothie.write(buf)
