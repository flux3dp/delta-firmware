
from struct import Struct
import logging

from fluxmonitor.misc.systime import systime
from fluxmonitor.config import CAMERA_ENDPOINT

from .handler import TextBinaryProtocol, SSLServerSideHandler, CloudHandler
from .tcp_ssl import SSLInterface
from .unixsocket import UnixStreamInterface, UnixStreamHandler, MsgpackMixIn

__all__ = ["CameraTcpInterface", "CameraTcpHandler",
           "CameraUnixStreamInterface", "CameraUnixStreamHandler"]
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


CMD_REQUEST_FRAME = 0x00
CMD_SCAN_CHECKING = 0x01
CMD_GET_BIAS = 0x02
CMD_COMPUTE_CAB = (0x03, 0x04, 0x05)
CMD_CLOUD_CONNECTION = 0x80


class CameraUnixStreamHandler(MsgpackMixIn, UnixStreamHandler):
    def __init__(self, *args, **kw):
        super(CameraUnixStreamHandler, self).__init__(*args, **kw)
        self.msgpack_init()

    def on_request(self, request):
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


class CameraUnixStreamInterface(UnixStreamInterface):
    def __init__(self, kernel, endpoint=CAMERA_ENDPOINT,
                 handler=CameraUnixStreamHandler):
        super(CameraUnixStreamInterface, self).__init__(kernel, endpoint,
                                                        handler)
