
import logging

logger = logging.getLogger(__name__)

import memcache

from fluxmonitor.event_base import EventBase
from fluxmonitor.misc import AsyncSignal


class FluxMonitor(EventBase):
    def __init__(self, module):
        super(FluxMonitor, self).__init__()

        self.self_test()
        self.cache = memcache.Client(["127.0.0.1:11211"])

        self.signal = AsyncSignal()
        self.add_read_event(self.signal)

        self.watcher = module(self)

    def run(self):
        self.watcher.start()
        EventBase.run(self)
        self.watcher.shutdown()

    def each_loop(self):
        self.watcher.each_loop()

    def shutdown(self, log):
        self.running = False
        self.signal.send()
        logger.info("Shutdown: %s" % log)

    def self_test(self):
        import platform
        import os
        if platform.system().lower().startswith("linux"):
            if os.getuid() != 0:
                raise RuntimeError("""======== WARNING ========
We found fluxmonitord is not running as root. fluxmonitord can not
run without root privilege under linux.
""")
