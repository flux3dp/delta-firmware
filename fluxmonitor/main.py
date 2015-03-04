
from time import sleep
import threading
import logging
import select
import sys
import os

logger = logging.getLogger(__name__)

import memcache

from fluxmonitor.misc import AsyncSignal
from fluxmonitor.watcher.network import NetworkWatcher
from fluxmonitor.watcher.wlan import WlanWatcher

class FluxMonitor(threading.Thread):
    def __init__(self):
        self.shared_mem = memcache.Client("127.0.0.1")
        self.signal = AsyncSignal()
        self.running = True

        self.watchers = [
            WlanWatcher(self.shared_mem),
            NetworkWatcher(self.shared_mem),
        ]

        super(FluxMonitor, self).__init__()

    def run(self):
        for w in self.watchers: w.start()
        while self.running:
            select.select((self.signal, ), (), (), 0.5)

    def shutdown(self, log=None):
        self.running = False
        self.signal.send()
        self.signal.close_write()
        for w in self.watchers: w.shutdown(log)
        logger.info(log)
