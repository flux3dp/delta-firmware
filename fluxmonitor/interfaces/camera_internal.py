
import logging
import socket
import os

from fluxmonitor.config import CAMERA_ENDPOINT
from .listener import UnixStreamInterface
from .handler import MsgpackProtocol, UnixHandler
from .camera import CameraUnixHandler

logger = logging.getLogger(__name__)
CMD_REQUEST_FRAME = 0x00
CMD_SCAN_CHECKING = 0x01
CMD_GET_BIAS = 0x02
CMD_COMPUTE_CAB = (0x03, 0x04, 0x05)
CMD_TRANSFER_TO_PUBLIC = 0x79
CMD_CLOUD_CONNECTION = 0x80


class CameraUnixStreamInterface(UnixStreamInterface):
    def __init__(self, kernel, endpoint=CAMERA_ENDPOINT):
        super(CameraUnixStreamInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        return CameraUnixStreamHandler(self.kernel, endpoint, sock)


class CameraUnixStreamHandler(MsgpackProtocol, UnixHandler):
    def on_connected(self):
        super(CameraUnixStreamHandler, self).on_connected()
        self.on_ready()

    def on_payload(self, request):
        if isinstance(request, tuple):
            try:
                cmd = request[0]
                camera_id = request[1]

                if cmd == CMD_REQUEST_FRAME:
                    mimetype, length, stream = self.kernel.makeshot(camera_id)
                    self.send_payload(("binary", mimetype, length))
                    self.begin_send(stream, length, lambda _: None)
                elif cmd == CMD_SCAN_CHECKING:
                    ret = self.kernel.scan_checking(camera_id)
                    self.send_payload(("ok", ret))
                elif cmd == CMD_GET_BIAS:
                    ret = self.kernel.get_bias(camera_id)
                    self.send_payload(("ok", ret))
                elif cmd in CMD_COMPUTE_CAB:
                    ret = self.kernel.compute_cab(camera_id, cmd)
                    self.send_payload(("ok", ret))
                elif cmd == CMD_TRANSFER_TO_PUBLIC:
                    newfd = os.dup(self.sock.fileno())
                    newsock = socket.fromfd(newfd, self.sock.family,
                                            self.sock.type)
                    h = CameraUnixHandler(self.kernel, "INTERNAL",
                                          sock=newsock)
                    self.kernel.public_ifce.clients.add(h)
                    self.kernel.on_connected(h)
                    self.close()
                elif cmd == CMD_CLOUD_CONNECTION:
                    endpoint = request[2]
                    token = request[3]
                    logger.debug("Recive connect2cloud request, endpoint=%s",
                                 endpoint)
                    ret = self.kernel.on_connect2cloud(camera_id, endpoint,
                                                       token)
                    self.send_payload(("ok", ret))
                else:
                    self.send_payload(("er", "UNKNOWN_COMMAND"))
            except RuntimeError as e:
                self.send_payload(("er", ) + e.args)
            except Exception:
                logger.exception("Error while exec camera unixsock cmd")
                self.send_payload(("er", "UNKNOWN_ERROR"))
                self.close()
        else:
            self.send_payload(("er", "UNKNOWN_COMMAND"))
            self.close()
