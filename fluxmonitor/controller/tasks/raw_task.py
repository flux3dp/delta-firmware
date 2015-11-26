
from fluxmonitor.err_codes import PROTOCOL_ERROR
from .base import DeviceOperationMixIn


class RawTask(DeviceOperationMixIn):
    def __init__(self, stack, handler):
        super(RawTask, self).__init__(stack, handler)
        handler.binary_mode = True

    def on_exit(self, handler):
        super(RawTask, self).on_exit(handler)
        handler.binary_mode = False

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
            if buf:
                self.handler.send(buf)
            else:
                self.on_dead(self, "DISCONNECTED")
        except Exception as e:
            self.on_dead(self, repr(e))

    def on_headboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
            if buf:
                self.handler.send(buf)
            else:
                self.on_dead(self, "DISCONNECTED")
        except Exception as e:
            self.on_dead(self, repr(e))

    def on_text(self, buf, handler):
        raise SystemError(PROTOCOL_ERROR, "RAW_MODE")

    def on_binary(self, buf, handler):
        if buf.startswith(b"+"):
            self._uart_mb.send(buf[1:])
        elif buf.startswith(b"-"):
            self._uart_hb.send(buf[1:])
        elif buf.startswith(b"1 "):
            self._uart_hb.send(buf)
        elif buf == b"quit":
            handler.binary_mode = False
            handler.send(b"\x00" * 64)
            handler.send(b"\x01")
            handler.send_text(b"ok")
            self.stack.exit_task(self, True)
        else:
            self._uart_mb.send(buf)
