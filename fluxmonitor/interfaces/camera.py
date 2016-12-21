
from struct import Struct
import logging

from fluxmonitor.misc.systime import systime

from .listener import SSLInterface
from .handler import (TextBinaryProtocol, SSLServerSideHandler, CloudHandler)

__all__ = ["CameraTcpInterface"]
UNIX_CMD_PACKER = Struct("@BB")
UINT_PACKER = Struct("<I")
BYTE_PACKER = Struct("@B")
logger = logging.getLogger(__name__)


class CameraTcpInterface(SSLInterface):
    def __init__(self, kernel, endpoint=("", 23812)):
        super(CameraTcpInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        logger.debug("Incomming connection from %s", endpoint)
        h = CameraTcpHandler(self.kernel, endpoint, sock, server_side=True,
                             certfile=self.certfile, keyfile=self.keyfile)
        self.kernel.on_connected(h)
        return h


class CameraProtocol(TextBinaryProtocol):
    streaming = False

    def on_ready(self):
        super(CameraProtocol, self).on_ready()
        self.ts = 0

    def on_text(self, text):
        if text == "f":
            if systime() - self.ts <= self.kernel.SPF:
                self.kernel.add_to_live_queue(self)
            else:
                self.next_frame()
        elif text == "s+":
            self.streaming = True
            logger.debug("Enable streaming")
            self.on_frame_sent()
        elif text == "s-":
            self.streaming = False
            logger.debug("Disable streaming")

    def on_frame_sent(self, _=None):
        if self.streaming:
            if systime() - self.ts <= self.kernel.SPF:
                self.kernel.add_to_live_queue(self)
            else:
                self.next_frame()

    def next_frame(self):
        try:
            logger.debug("Next frame")
            self.ts, imageobj = self.kernel.live(0)
            mimetype, length, stream = imageobj
            self.send(UINT_PACKER.pack(length))
            self.begin_send(stream, length, self.on_frame_sent)
        except IOError as e:
            logger.debug("%s", e)
            self.close()

    def on_close(self, handler):
        pass


class CameraTcpHandler(CameraProtocol, SSLServerSideHandler):
    def on_authorized(self):
        super(CameraTcpHandler, self).on_authorized()
        self.on_ready()


class CameraCloudHandler(CameraProtocol, CloudHandler):
    def on_cloud_connected(self):
        super(CameraCloudHandler, self).on_cloud_connected()
        self.on_ready()
