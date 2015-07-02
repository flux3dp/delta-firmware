
from .base import ExclusiveMixIn, DeviceOperationMixIn


class RawTask(ExclusiveMixIn, DeviceOperationMixIn):
    def __init__(self, server, sender):
        super(RawTask, self).__init__(server, sender)
        self.connect()
        sender.binary_mode = True

    def on_mainboard_message(self, sender):
        try:
            buf = sender.obj.recv(4096)
            self.owner().send(buf)
        except Exception as e:
            self.on_dead(self, repr(e))

    def on_headboard_message(self, sender):
        try:
            buf = sender.obj.recv(4096)
            self.owner().send(buf)
        except Exception as e:
            self.on_dead(self, repr(e))

    def on_owner_message(self, buf, sender):
        if buf.startswith(b"+"):
            self._uart_mb.send(buf[1:])
        elif buf.startswith(b"-"):
            self._uart_hb.send(buf[1:])
        elif buf.startswith(b"L") or buf.startswith(b"H"):
            self._uart_hb.send(buf)
        elif buf == b"quit":
            sender.binary_mode = False
            sender.send_text(b"ok")
            self.disconnect()
            self.server.exit_task(self, True)
        else:
            self._uart_mb.send(buf)
