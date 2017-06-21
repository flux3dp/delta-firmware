
from fluxmonitor.err_codes import PROTOCOL_ERROR
from fluxmonitor.storage import metadata
from fluxmonitor.hal import tools

from .base import DeviceOperationMixIn


class RawTask(DeviceOperationMixIn):
    st_id = -10
    toolhead_on = False

    def __init__(self, stack, handler):
        super(RawTask, self).__init__(stack, handler)
        handler.binary_mode = True
        metadata.update_device_status(self.st_id, 0, "N/A", handler.address)

    def clean(self):
        metadata.update_device_status(0, 0, "N/A", "")
        tools.toolhead_standby()

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(4096)
            if buf:
                if self.handler.interface == "TCP":
                    self.handler.send(buf)
                else:
                    self.handler.send_binary(buf)
            else:
                self.on_dead("DISCONNECTED")
        except Exception as e:
            self.on_dead(repr(e))

    def on_headboard_message(self, watcher, revent):
        if self.toolhead_on is False:
            tools.toolhead_on()
            self.toolhead_on = True

        try:
            buf = watcher.data.recv(4096)
            if buf:
                if self.handler.interface == "TCP":
                    self.handler.send(buf)
                else:
                    self.handler.send_binary(buf)
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
            self._sock_mb.send(buf[1:])
        elif buf.startswith(b"-"):
            self._sock_th.send(buf[1:])
        elif buf.startswith(b"1 "):
            self._sock_th.send(buf)
        elif buf == b"quit":
            handler.binary_mode = False
            if self.handler.interface == "TCP":
                handler.send(b"\x00" * 64)
                handler.send(b"\x01")
            handler.send_text(b"ok")
            self.stack.exit_task(self, True)
        else:
            self._sock_mb.send(buf)
