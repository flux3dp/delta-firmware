
import logging
import os

logger = logging.getLogger(__name__)


from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.config import general_config
from .base import UartHalBase


class UartHal(UartHalBase):
    hal_name = "dev"

    def __init__(self, server):
        super(UartHal, self).__init__(server)

        p = general_config["db"]
        self.listen_mainboard = self.create_socket(os.path.join(p, "mb"))
        self.listen_headboard = self.create_socket(os.path.join(p, "hb"))
        self.listen_pc = self.create_socket(os.path.join(p, "pc"))
        server.add_read_event(
            AsyncIO(self.listen_mainboard, self.on_fake_mainboard_connected))
        server.add_read_event(
            AsyncIO(self.listen_headboard, self.on_fake_headboard_connected))
        server.add_read_event(
            AsyncIO(self.listen_pc, self.on_fake_pc_connected))

        self.fake_mainboard_socks = []
        self.fake_headboard_socks = []
        self.fake_pc_socks = []

    def on_fake_mainboard_connected(self, sender):
        logger.debug("Connect from mainboard")
        request, _ = sender.obj.accept()
        self.fake_mainboard_socks.append(request)
        self.server.add_read_event(
            AsyncIO(request, self.on_recvfrom_mainboard))

    def on_fake_headboard_connected(self, sender):
        logger.debug("Connect from headboard")
        request, _ = sender.obj.accept()
        self.fake_headboard_socks.append(request)
        self.server.add_read_event(
            AsyncIO(request, self.on_recvfrom_headboard))

    def on_fake_pc_connected(self, sender):
        logger.debug("Connect from pc")
        request, _ = sender.obj.accept()
        self.fake_pc_socks.append(request)
        self.server.add_read_event(
            AsyncIO(request, self.on_recvfrom_pc))

    def on_recvfrom_mainboard(self, sender):
        buf = sender.obj.recv(1024)
        if buf:
            for sock in self.mainboard_socks:
                sock.send(buf)
        else:
            self.server.remove_read_event(sender)
            self.fake_mainboard_socks.remove(sender.obj)

    def on_recvfrom_headboard(self, sender):
        buf = sender.obj.recv(1024)
        if buf:
            for sock in self.headboard_socks:
                sock.send(buf)
        else:
            self.server.remove_read_event(sender)
            self.fake_headboard_socks.remove(sender.obj)

    def on_recvfrom_pc(self, sender):
        buf = sender.obj.recv(1024)
        if buf:
            for sock in self.pc_socks:
                sock.send(buf)
        else:
            self.server.remove_read_event(sender)
            self.fake_pc_socks.remove(sender.obj)

    def sendto_mainboard(self, buf):
        for sock in self.fake_mainboard_socks:
            sock.send(buf)

    def sendto_headboard(self, buf):
        for sock in self.fake_headboard_socks:
            sock.send(buf)

    def sendto_pc(self, buf):
        for sock in self.fake_pc_socks:
            sock.send(buf)
