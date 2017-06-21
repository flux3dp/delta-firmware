
import logging
import socket
import pyev

from fluxmonitor.config import CAMERA_ENDPOINT

logger = logging.getLogger(__name__)


class CameraChannel(object):
    def __init__(self, index, protocol):
        self.index = index
        self.protocol = protocol
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(CAMERA_ENDPOINT)
        self.sock.send(b'\x92y\xc0')
        self.watcher = protocol.kernel.loop.io(
            self.sock.fileno(), pyev.EV_READ, self.handle_sock_recv)
        self.watcher.start()
        logger.debug("Camera channel opened")

    def __str__(self):
        return "<CameraChannel@%i>" % (self.index)

    def handle_sock_recv(self, *args):
        try:
            b = self.sock.recv(256)
            self.watcher.stop()
            if b:
                self.protocol.send_binary(self.index, b)
            else:
                logger.debug("%s Close channel", self)
                self.protocol.close_channel(self.index)
        except IOError as e:
            logger.debug("%s %s, close channel", self, e)
            self.protocol.close_channel(self.index)
        except Exception:
            logger.exception("Unhandle error, close channel")
            self.protocol.close_channel(self.index)

    def on_payload(self, obj):
        logger.error("Camera channel does not support payload message")

    def on_binary(self, buf):
        try:
            self.sock.send(buf)
        except IOError as e:
            logger.debug("%s, close channel", e)
            self.protocol.close_channel(self.index)
        except Exception:
            logger.exception("Unhandle error, close channel")
            self.protocol.close_channel(self.index)

    def on_binary_ack(self):
        self.watcher.start()

    def close(self):
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if self.sock:
            self.sock.close()
            self.sock = None
            logger.debug("Camera channel closed")
