
import logging
import socket

from fluxmonitor.config import uart_config


class ButtonControl(object):
    def __init__(self, kernel, logger=None):
        self.logger = logger.getChild("bc") if logger \
            else logging.getLogger(__name__)

        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(uart_config["control"])

        kernel.add_read_event(self)
        self._buf = ""

    def fileno(self):
        return self.sock.fileno()

    def on_read(self, kernel):
        self._buf += self.sock.recv(8 - len(self._buf))
        if len(self._buf) == 8:
            try:
                kernel.on_button_control(self._buf.strip())
            except Exception:
                self.logger.exception("Unhandle error")
            finally:
                self._buf = ""

    def close(self, kernel):
        self.sock.close()
        kernel.remove_read_event(self)
