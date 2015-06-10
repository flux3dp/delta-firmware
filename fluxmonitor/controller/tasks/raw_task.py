
from fluxmonitor.err_codes import RESOURCE_BUSY
from .base import ExclusiveMixIn, DeviceOperationMixIn


class RawTask(ExclusiveMixIn, DeviceOperationMixIn):
    def __init__(self, server, sender):
        super(RawTask, self).__init__(server, sender)
        self.connect()

    def on_dead(self, sender, reason=None):
        try:
            self.disconnect()
        finally:
            super(RawTask, self).on_dead(sender, reason)

    def on_mainboard_message(self, sender):
        try:
            buf = sender.obj.recv(4096)
            self.owner().send(buf)
        except Exception as e:
            self.on_dead(repr(e))

    def on_headboard_message(self, sender):
        try:
            buf = sender.obj.recv(4096)
            self.owner().send(buf)
        except Exception as e:
            self.on_dead(repr(e))

    def on_message(self, buf, sender):
        buf = buf.rstrip("\x00")

        if self.owner() == sender:
            if buf.startswith(b"+"):
                self._uart_mb.send(buf[1:])
            elif buf.startswith(b"-"):
                self._uart_hb.send(buf[1:])
            elif buf.startswith(b"L") or buf.startswith(b"H"):
                self._uart_hb.send(buf)
            elif buf == b"quit":
                sender.send(b"ok")
                self.disconnect()
                self.server.exit_task(self, True)
            else:
                self._uart_mb.send(buf)
        else:
            if buf == b"kick":
                self.on_dead(self.sender, "Kicked")
                sender.send("kicked")
            else:
                sender.send(("error %s raw" % RESOURCE_BUSY).encode())
