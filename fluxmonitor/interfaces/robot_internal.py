
import logging

from fluxmonitor.config import ROBOT_ENDPOINT
from .listener import UnixStreamInterface
from .handler import MsgpackProtocol, UnixHandler

logger = logging.getLogger(__name__)
CMD_CLOUD_CONNECTION = 0x80


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
