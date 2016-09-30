
import msgpack
import logging

from .handler import UDPHandler

logger = logging.getLogger(__name__)

ACTION_REQUEST_CAMERA = 0x80
ACTION_REQUEST_CONTROL = 0x90


class CloudUdpSyncHander(UDPHandler):
    udp_timestemp = 0

    def __init__(self, kernel, endpoint, timestemp, session):
        super(CloudUdpSyncHander, self).__init__(kernel, endpoint)
        self.udp_timestemp = timestemp
        self.session = session

    def send(self, buf):
        payload = self.session.pack(buf)
        super(CloudUdpSyncHander, self).send(payload)

    def sendto(self, *args):
        # This method should not be use
        raise RuntimeError("BAN")

    def on_message(self, buf, endpoint):
        try:
            if buf.startswith(b"\x00"):
                return
            elif buf.startswith(b"\x01"):
                message = self.session.unpack(buf[1:])
                if message:
                    self.process_message(message)
                else:
                    logger.error("UDP recv illegal payload")
            else:
                logger.error("Unknown udp payload prefix: %s", buf[0])
        except Exception:
            logger.exception("UDP payload error, drop")
            raise

    def process_message(self, message):
        request = msgpack.unpackb(message)
        timestemp = request[0]
        if timestemp > self.udp_timestemp:
            self.udp_timestemp = timestemp
            try:
                self.handle_request(request[1], *request[2:])
            except RuntimeWarning as e:
                logger.error("%s", e)
        else:
            logger.error("UDP Timestemp error. Current %f buf got %f",
                         self.udp_timestemp, timestemp)

    def handle_request(self, action_id, *args):
        if action_id == ACTION_REQUEST_CAMERA:
            if len(args) == 3:
                self.kernel.require_camera(args[0], args[1], args[2])
            else:
                raise RuntimeWarning("Bad params for request camera")
        elif action_id == ACTION_REQUEST_CONTROL:
            if len(args) == 2:
                self.kernel.require_control(args[0], args[1])
            else:
                raise RuntimeWarning("Bad params for request control")
        else:
            raise RuntimeWarning("Bad request action id")
        self.send(msgpack.packb((action_id, )))
