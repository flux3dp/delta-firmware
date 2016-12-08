
from fluxmonitor.interfaces.robot import ServiceStack
import logging

logger = logging.getLogger(__name__)


class RobotChannel(object):
    interface = "USB"
    binary_mode = False

    def __init__(self, index, protocol):
        self.index = index
        self.protocol = protocol
        self.stack = ServiceStack(self.protocol.kernel)
        self._binary_ack = 0

    @property
    def address(self):
        return "USB#%i" % (self.index)

    def __str__(self):
        return "<RobotChannel@%i>" % (self.index)

    def send_text(self, string):
        self.protocol.send_payload(self.index, string)

    def send_binary(self, buf):
        self.protocol.send_binary(self.index, buf)

    def async_send_binary(self, mimetype, length, stream, cb):
        self.protocol.send_payload(self.index,
                                   "binary %s %i" % (mimetype, length))
        self.protocol.begin_send(self.index, stream, length, cb)

    def on_payload(self, obj):
        self.stack.on_text(" ".join("%s" % i for i in obj), self)

    def on_binary(self, buf):
        self._binary_ack += 1
        self.stack.on_binary(buf, self)
        if self._binary_ack <= 0:
            logger.error("binary ack=%i after send", self._binary_ack)
        elif self._binary_ack > 16:
            logger.error("binary ack=%i", self._binary_ack)

    def on_binary_ack(self):
        self._binary_ack -= 1

    def close(self):
        self.stack.on_close(self)
        self.stack = None
