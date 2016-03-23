
from weakref import proxy
from struct import Struct
import logging
import os

from fluxmonitor.config import CAMERA_ENDPOINT

from .tcp import TcpInterface, TcpConnectionHandler
from .unixsocket import UnixStreamInterface, UnixStreamHandler

__all__ = ["CameraTcpInterface", "CameraTcpHandler",
           "CameraUnixStreamInterface", "CameraUnixStreamHandler"]
UNIX_CMD_PACKER = Struct("@BB")
BYTE_PACKER = Struct("@B")
logger = logging.getLogger(__name__)


class CameraTcpInterface(TcpInterface):
    def __init__(self, kernel, endpoint=("", 23812)):
        super(CameraTcpInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        return CameraTcpHandler(self.kernel, sock, endpoint, self.privatekey)


class CameraTcpHandler(TcpConnectionHandler):
    def on_ready(self):
        # TODO
        self.delegate = proxy(self.kernel)


class CameraUnixStreamInterface(UnixStreamInterface):
    def __init__(self, kernel, endpoint=CAMERA_ENDPOINT):
        super(CameraUnixStreamInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        h = CameraUnixStreamHandler(self.kernel, sock, endpoint)
        self.kernel.internal_conn.add(h)
        self.kernel.update_camera_status()
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
                    ret = self.kernel.scan_checking()
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
