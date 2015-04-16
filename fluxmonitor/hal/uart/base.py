
import logging
import socket
import os

logger = logging.getLogger(__name__)


from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.config import uart_config

class UartHalBase(object):
    hal_name = "BASE"

    def __init__(self, server):
        self.mainboard = self.create_socket(uart_config["mainboard"])
        self.headboard = self.create_socket(uart_config["headboard"])
        self.pc = self.create_socket(uart_config["pc"])

        self.mainboard_socks = []
        self.headboard_socks = []
        self.pc_socks = []

        server.add_read_event(
            AsyncIO(self.mainboard, self.on_connected_mainboard))
        server.add_read_event(
            AsyncIO(self.headboard, self.on_connected_headboard))
        server.add_read_event(
            AsyncIO(self.pc, self.on_connected_pc))

        self.server = server
        
    def create_socket(self, path):
        if os.path.exists(path):
            os.unlink(path)

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(path)
        s.listen(1)

        return s

    def on_connected_mainboard(self, sender):
        logger.debug("Connect to mainboard")
        request, _ = sender.obj.accept()
        self.mainboard_socks.append(request)
        self.server.add_read_event(AsyncIO(request, self.on_sendto_mainboard))

    def on_connected_headboard(self, sender):
        logger.debug("Connect to headboard")
        request, _ = sender.obj.accept()
        self.headboard_socks.append(request)
        self.server.add_read_event(AsyncIO(request, self.on_sendto_headboard))

    def on_connected_pc(self, sender):
        logger.debug("Connect to pc")
        request, _ = sender.obj.accept()
        self.pc_socks.append(request)
        self.server.add_read_event(AsyncIO(request, self.on_sendto_pc))

    def on_sendto_mainboard(self, sender):
        buf = sender.obj.recv(1024)
        if buf:
            self.sendto_mainboard(buf)
        else:
            self.server.remove_read_event(sender)
            self.mainboard_socks.remove(sender.obj)

    def on_sendto_headboard(self, sender):
        buf = sender.obj.recv(1024)
        if buf:
            self.sendto_headboard(buf)
        else:
            self.server.remove_read_event(sender)
            self.headboard_socks.remove(sender.obj)

    def on_sendto_pc(self, sender):
        buf = sender.obj.recv(1024)
        if buf:
            self.sendto_pc(buf)
        else:
            self.server.remove_read_event(sender)
            self.pc_socks.remove(sender.obj)

    def sendto_mainboard(self, buf):
        pass

    def sendto_headboard(self, buf):
        pass

    def sendto_pc(self, buf):
        pass


class BaseOnSerial(object):
    def on_recvfrom_mainboard(self, sender):
        buf = sender.obj.readall()
        for sock in self.mainboard_socks:
            sock.send(buf)

    def on_recvfrom_headboard(self, sender):
        buf = sender.obj.readall()
        for sock in self.headboard_socks:
            sock.send(buf)

    def on_recvfrom_pc(self, sender):
        buf = sender.obj.readall()
        for sock in self.pc_socks:
            sock.send(buf)
