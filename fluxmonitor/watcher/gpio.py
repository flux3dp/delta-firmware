
from time import sleep
import threading
import socket
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.config import button_config, develope_env
from fluxmonitor.misc.async_signal import AsyncIO
from .base import WatcherBase


class GpioWatcher(WatcherBase):
    """GpioWatcher is a bridge beteen GPIO and socket interface

    Because GPIO operation require root privilege. GpioWatcher will
    monitor GPIO status and pass message to unixsocket."""

    def __init__(self, memcache):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(button_config["unixsocket"])
        sock.listen(2)
        self.clients = []
        self.rlist.append(AsyncIO(sock, self._on_incomming_connection))

        super(GpioWatcher, self).__init__(logger, memcache)

    def run(self):
        GpioInterface(self)
        super(GpioWatcher, self).run()

    def _on_incomming_connection(self, sender):
        sock, addr = sender.obj.accept()
        self.clients.append(sock)

        # Remote should not send and message right now, just shut it up
        self.rlist.append(AsyncIO(sock, self._on_remote_close))


class GpioInterface(threading.Thread):
    """GPIO status must query by itself. We create a standalone thread
    and monitor GPIO status every 0.1 seconds"""

    SLEEP_DURATION = 0.1

    def __init__(self, watcher):
        self.watcher = watcher
        super(GpioInterface, self).__init__()
        self.setDaemon(True)
        self.start()

    def run(self):
        while self.watcher.isAlive():
            
            sleep(self.SLEEP_DURATION)

