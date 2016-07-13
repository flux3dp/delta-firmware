
from weakref import proxy
from struct import Struct
import logging
import os

from fluxmonitor.misc.systime import systime
from fluxmonitor.config import CAMERA_ENDPOINT

from .tcp_ssl import SSLInterface, SSLConnectionHandler
from .unixsocket import UnixStreamInterface, UnixStreamHandler

__all__ = ["CameraTcpInterface", "CameraTcpHandler",
           "CameraUnixStreamInterface", "CameraUnixStreamHandler"]
UNIX_CMD_PACKER = Struct("@BB")
UINT_PACKER = Struct("<I")
BYTE_PACKER = Struct("@B")
logger = logging.getLogger(__name__)


class CameraTcpInterface(SSLInterface):
    _empty = True

    def __init__(self, kernel, endpoint=("", 23812)):
        super(CameraTcpInterface, self).__init__(kernel, endpoint)

    def on_timer(self, watcher, revent):
        super(CameraTcpInterface, self).on_timer(watcher, revent)
        if not self.clients and self._empty is False:
            self._empty = True
            self.kernel.on_client_gone()

    def create_handler(self, sock, endpoint):
        h = CameraTcpHandler(self.kernel, sock, endpoint,
                             self.certfile, self.keyfile)
        if self._empty is True:
            self._empty = False
            self.kernel.on_client_connected()
        return h


class CameraTcpHandler(SSLConnectionHandler):
    streaming = False

    def on_ready(self):
        self.delegate = proxy(self)
        self.ts = 0

    def on_text(self, text, _):
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
        logger.debug("Next frame")
        self.ts, imageobj = self.kernel.live(0)
        mimetype, length, stream = imageobj
        self.send(UINT_PACKER.pack(length))
        self.begin_send(stream, length, self.on_frame_sent)

    def on_close(self, handler):
        pass


class CameraUnixStreamInterface(UnixStreamInterface):
    _empty = True

    def __init__(self, kernel, endpoint=CAMERA_ENDPOINT):
        super(CameraUnixStreamInterface, self).__init__(kernel, endpoint)

    def on_timer(self, watcher, revent):
        super(CameraUnixStreamInterface, self).on_timer(watcher, revent)
        if not self.clients and self._empty is False:
            self._empty = True
            self.kernel.on_client_gone()

    def create_handler(self, sock, endpoint):
        h = CameraUnixStreamHandler(self.kernel, sock, endpoint)
        if self._empty is True:
            self._empty = False
            self.kernel.on_client_connected()
        return h

    def close(self):
        super(CameraUnixStreamInterface, self).close()
        os.unlink(CAMERA_ENDPOINT)


class CameraUnixStreamHandler(UnixStreamHandler):
    buf = b""

    def send_text(self, message):
        buf = BYTE_PACKER.pack(len(message)) + message
        self.send(buf)

    def on_recv(self, watcher, revent):
        buf = self.sock.recv(2 - len(self.buf))
        if not buf:
            self.close()
        self.buf += buf

        while len(self.buf) >= 2:
            request = self.buf[:2]
            self.buf = self.buf[2:]
            cmd_id, camera_id = UNIX_CMD_PACKER.unpack(request)

            try:
                if cmd_id == 0:
                    mimetype, length, stream = self.kernel.makeshot(camera_id)
                    self.send_text("binary %s %i" % (mimetype, length))
                    self.begin_send(stream, length, lambda _: None)

                elif cmd_id == 1:
                    ret = self.kernel.scan_checking(camera_id)
                    self.send_text("ok %s" % ret)

                elif cmd_id == 2:
                    ret = self.kernel.get_bias(camera_id)
                    self.send_text("ok {}".format(ret))

                elif cmd_id >= 3 and cmd_id <= 5:
                    ret = self.kernel.compute_cab(camera_id, cmd_id)
                    self.send_text("ok {}".format(ret))

                else:
                    self.send_text("er UNKNOWN_COMMAND")
            except Exception as e:
                self.send_text("er UNKNOWN_ERROR {}".format(e))
                logger.exception("Error while exec camera unixsock cmd")
