
import logging
import socket

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.event_base import EventBase
from fluxmonitor.config import uart_config

from fluxmonitor.controller.interfaces.local import LocalControl

logger = logging.getLogger("fluxrobot")


class Robot(EventBase):
    def __init__(self, options):
        EventBase.__init__(self)

        self.local_control = LocalControl(self, logger=logger)

        self.uart_mb = u_mb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.uart_hb = u_hb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        u_mb.connect(uart_config["mainboard"])
        u_hb.connect(uart_config["headboard"])

        self.add_read_event(AsyncIO(u_mb, self.on_mainboard_message))
        self.add_read_event(AsyncIO(u_hb, self.on_headboard_message))

    def on_cmd(self, cmd, sock):
        pass

    def on_mainboard_message(self, sender):
        pass

    def on_headboard_message(self, sender):
        pass

    def each_loop(self):
        pass
