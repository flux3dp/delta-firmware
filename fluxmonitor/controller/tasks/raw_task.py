
from fluxmonitor.err_codes import PROTOCOL_ERROR
from fluxmonitor.storage import metadata

from .base import DeviceOperationMixIn


class RawTask(DeviceOperationMixIn):
    st_id = -10

    def __init__(self, stack, handler):
        super(RawTask, self).__init__(stack, handler)
        handler.binary_mode = True
        metadata.update_device_status(self.st_id, 0, "N/A", handler.address)

    def clean(self):
        metadata.update_device_status(0, 0, "N/A", "")

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
            if buf:
                if self.handler.interface == "TCP":
                    self.handler.send_text(buf)
                else:
                    self.handler.send_binary(buf)
            else:
                self.on_dead("DISCONNECTED")
        except Exception as e:
            self.on_dead(repr(e))

    def on_headboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
            if buf:
                if self.handler.interface == "TCP":
                    self.handler.send(buf)
                else:
                    self.handler.send_text(buf)
            else:
                self.on_dead("DISCONNECTED")
        except Exception as e:
            self.on_dead(repr(e))

    def on_text(self, buf, handler):
        raise SystemError(PROTOCOL_ERROR, "RAW_MODE")

    def on_binary(self, buf, handler):
        if isinstance(buf, memoryview):
            buf = buf.tobytes()

        if buf.startswith(b"+"):
            self._uart_mb.send(buf[1:])
        elif buf.startswith(b"-"):
            self._uart_hb.send(buf[1:])
        elif buf.startswith(b"1 "):
            self._uart_hb.send(buf)
        elif buf == b"quit":
            handler.binary_mode = False
            if self.handler.interface == "TCP":
                handler.send(b"\x00" * 64)
                handler.send(b"\x01")
            handler.send_text(b"ok")
            self.stack.exit_task(self, True)
        else:
            self._uart_mb.send(buf)
