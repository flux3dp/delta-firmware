
import logging
import socket
import os
from .base import InterfaceBase, HandlerBase

__all__ = ["UnixStreamInterface", "UnixStreamHandler"]
logger = logging.getLogger(__name__)


class UnixStreamInterface(InterfaceBase):
    def create_socket(self, endpoint):
        if os.path.exists(endpoint):
            logger.info("Unlink '%s' for new unix socket", endpoint)
            os.unlink(endpoint)
        logger.info("Listen on '%s'", endpoint)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(endpoint)
        s.listen(2)
        return s


class UnixStreamHandler(HandlerBase):
    def send(self, message):
        buf = memoryview(message)
        length = len(message)

        sent = self.sock.send(buf)
        while sent < length:
            sent += self.sock.send(buf[sent:])
        return length
