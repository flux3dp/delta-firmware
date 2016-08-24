
import logging
import msgpack
import socket
import os
from .base import InterfaceBase, HandlerBase

__all__ = ["UnixStreamInterface", "UnixStreamHandler"]
logger = logging.getLogger(__name__)


# class UnixDatagramInterface(InterfaceBase):
#     def create_socket(self, endpoint):
#         if os.path.exists(endpoint):
#             logger.info("Unlink '%s' for new unix socket", endpoint)
#             os.unlink(endpoint)
#         logger.info("Listen on '%s'", endpoint)
#         s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
#         s.bind(endpoint)
#         s.listen(2)
#         return s

#     def close(self):
#         endpoint = self.getsockname()
#         super(UnixDatagramInterface, self).close()
#         os.unlink(endpoint)


class UnixStreamInterface(InterfaceBase):
    def __init__(self, kernel, endpoint, handler):
        super(UnixStreamInterface, self).__init__(kernel, endpoint, handler)

    def create_socket(self, endpoint):
        if os.path.exists(endpoint):
            logger.info("Unlink '%s' for new unix socket", endpoint)
            os.unlink(endpoint)
        logger.info("Listen on '%s'", endpoint)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(endpoint)
        s.listen(2)
        return s

    def close(self):
        endpoint = self.getsocket().getsockname()
        super(UnixStreamInterface, self).close()
        os.unlink(endpoint)


class UnixStreamHandler(HandlerBase):
    def send(self, message):
        if len(message) > 1024:
            buf = memoryview(message)
            length = len(message)

            sent = self.sock.send(buf)
            while sent < length:
                sent += self.sock.send(buf[sent:])
            return length
        else:
            return self.sock.send(message)


class MsgpackMixIn(object):
    def msgpack_init(self, max_buffer_size=2048):
        self.unpacker = msgpack.Unpacker(use_list=False,
                                         max_buffer_size=max_buffer_size)

    def send_payload(self, payload):
        buf = msgpack.packb(payload)
        self.send(buf)

    def on_recv(self, watcher, revent):
        try:
            buf = self.sock.recv(4096)
            if buf:
                self.unpacker.feed(buf)
                for data in self.unpacker:
                    self.on_request(data)
            else:
                self.close()
        except:
            self.close()
            raise
