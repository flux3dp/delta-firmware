
import logging
import socket

__all__ = ["UnixStreamInterface", "UnixStreamHandler"]
logger = logging.getLogger(__name__)


class UnixStreamInterface(object):
    def create_socket(self, endpoint):
        logger.info("Listen on '%s'", endpoint)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(endpoint)
        s.listen(2)
        return s


class UnixStreamHandler(object):
    def send(self, message):
        buf = memoryview(message)
        length = len(message)

        sent = self.sock.send(buf)
        while sent < length:
            sent += self.sock.send(buf[sent:])
        return length
