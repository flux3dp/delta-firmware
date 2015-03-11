
import threading
import logging
import select

logger = logging.getLogger(__name__)

import memcache

from fluxmonitor.misc import AsyncSignal
from fluxmonitor.watcher.network import NetworkWatcher


class FluxMonitor(threading.Thread):
    def __init__(self):
        self.self_test()
        self.shared_mem = memcache.Client("127.0.0.1")
        self.signal = AsyncSignal()
        self.running = True

        self.watchers = [
            NetworkWatcher(self.shared_mem),
        ]

        super(FluxMonitor, self).__init__()

    def run(self):
        for w in self.watchers:
            w.start()
        while self.running:
            select.select((self.signal, ), (), (), 0.5)

    def self_test(self):
        import platform
        import os
        if platform.system().lower().startswith("linux"):
            if os.getuid() != 0:
                raise RuntimeError("""======== WARNING ========
We found fluxmonitord is not running as root. fluxmonitord can not
run without root privilege under linux.
""")

    def shutdown(self, log=None):
        self.running = False
        self.signal.send()
        self.signal.close_write()
        for w in self.watchers:
            w.shutdown(log)
        logger.info(log)
