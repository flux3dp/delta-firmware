
import logging
import socket

import pyev

from fluxmonitor.config import uart_config

logger = logging.getLogger("halservice.rasp")


class ButtonControl(object):
    def __init__(self, kernel, logger=None):
        self.logger = logger.getChild("bc") if logger \
            else logging.getLogger(__name__)

        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(uart_config["control"])

        self.watcher = kernel.loop.io(self.sock, pyev.EV_READ, self.on_message,
                                      kernel)
        self.watcher.start()
        self._buf = ""

    @property
    def running(self):
        return self.watcher.active

    def on_message(self, watcher, revent):
        buf = self.sock.recv(8 - len(self._buf))
        if buf:
            self._buf += buf
            if len(self._buf) == 8:
                try:
                    watcher.data.on_button_control(self._buf.strip())
                except Exception:
                    self.logger.exception("Unhandle error")
                finally:
                    self._buf = ""
        else:
            logger.error("Button control disconnected.")
            watcher.stop()

    def close(self):
        self.watcher.stop()
        self.watcher = None
        self.sock.close()
