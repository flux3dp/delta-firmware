
from multiprocessing.reduction import recv_handle
from select import select
import logging
import socket

from fluxmonitor.config import ROBOT_ENDPOINT
from .listener import UnixStreamInterface
from .handler import MsgpackProtocol, UnixHandler

logger = logging.getLogger(__name__)
CMD_CLOUD_CONNECTION = 0x80
CMD_USBCABEL_CONNECTION = 0x81


class RobotUnixStreamInterface(UnixStreamInterface):
    def __init__(self, kernel, endpoint=ROBOT_ENDPOINT):
        super(RobotUnixStreamInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        return RobotUnixStreamHandler(self.kernel, endpoint, sock)


class RobotUnixStreamHandler(MsgpackProtocol, UnixHandler):
    def on_connected(self):
        super(RobotUnixStreamHandler, self).on_connected()
        self.on_ready()

    def on_payload(self, request):
        if isinstance(request, tuple):
            try:
                cmd = request[0]

                if cmd == CMD_CLOUD_CONNECTION:
                    endpoint = request[1]
                    token = request[2]
                    logger.debug("Recive connect2cloud request, endpoint=%s",
                                 endpoint)
                    ret = self.kernel.on_connect2cloud(endpoint, token)
                    self.send_payload(("ok", ret))
                    self.close()

                elif cmd == CMD_USBCABEL_CONNECTION:
                    self.send(b"F")
                    rl = select((self.sock, ), (), (), 0.1)[0]
                    if rl:
                        fd = recv_handle(self.sock)
                        usbsock = socket.fromfd(fd, socket.AF_UNIX,
                                                socket.SOCK_STREAM)
                        self.kernel.on_connect2usb(usbsock)
                        self.send(b"X")
                        self.close()
                    else:
                        self.send(b"I")
                        self.close()
                else:
                    self.send_payload(("er", "UNKNOWN_COMMAND"))
            except RuntimeError as e:
                self.send_payload(("er", ) + e.args)
            except Exception:
                logger.exception("Error in internal socket")
                self.send_payload(("er", "UNKNOWN_ERROR"))
                self.close()
        else:
            self.send_payload(("er", "UNKNOWN_COMMAND"))
            self.close()
