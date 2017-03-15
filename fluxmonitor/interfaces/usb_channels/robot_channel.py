
from fluxmonitor.interfaces.robot import ServiceStack
import logging

logger = logging.getLogger(__name__)


class RobotChannel(object):
    interface = "USB"
    binary_mode = False
    _binary_data = None

    def __init__(self, index, protocol):
        self.index = index
        self.protocol = protocol
        self.stack = ServiceStack(self.protocol.kernel)

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
        self._binary_data = (length, 0, stream, cb)
        self.protocol.send_payload(self.index,
                                   "binary %s %i" % (mimetype, length))
        self._feed_binary()

    def on_payload(self, obj):
        self.stack.on_text(" ".join("%s" % i for i in obj), self)

    def on_binary(self, buf):
        self.stack.on_binary(buf, self)

    def on_binary_ack(self):
        if self._binary_data:
            self._feed_binary()
        else:
            logger.debug("Recv unkandle binary ack")

    def _feed_binary(self):
        try:
            length, sent_length, stream, callback = self._binary_data

            if length == sent_length:
                self._binary_data = None
                callback(self)
                return

            bdata = stream.read(min(length - sent_length, 508))
            self.protocol.send_binary(self.index, bdata)
            sent_length += len(bdata)
            self._binary_data = (length, sent_length, stream, callback)

        except IOError as e:
            logger.debug("Send error: %s", e)
            self.protocol.on_error()
        except Exception:
            logger.exception("Unknow error")
            self.protocol.on_error()

    def close(self):
        if self._binary_data:
            length, sent_length = self._binary_data[:2]
        if self.stack:
            self.stack.on_close(self)
            self.stack = None
            self.on_payload = lambda obj: self.send_text("error CLOSED")
            self.on_binary = lambda buf: None
