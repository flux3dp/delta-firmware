
from errno import EINTR
import logging
import select

logger = logging.getLogger(__name__)

import memcache

from fluxmonitor.misc import AsyncSignal


class EventBase(object):
    POLL_TIMEOUT = 5.0

    def __init__(self):
        self.rlist = []

    def add_read_event(self, fd_obj):
        self.rlist.append(fd_obj)

    def remove_read_event(self, fd_obj):
        if fd_obj in self.rlist:
            self.rlist.remove(fd_obj)
            return True
        else:
            return False

    def run(self):
        self.running = True

        while self.running:
            try:
                rlist, wlist, xlist = select.select(self.rlist,
                                                    (),
                                                    (),
                                                    self.POLL_TIMEOUT)
            except select.error as err:
                if err.args[0] == EINTR:
                    continue
                else:
                    raise

            for r in rlist:
                try:
                    r.on_read()
                except Exception:
                    logger.exception("Unhandle error")

            try:
                self.each_loop()
            except Exception:
                logger.exception("Unhandle error")


class FluxMonitor(EventBase):
    def __init__(self, module):
        EventBase.__init__(self)

        self.self_test()
        self.cache = memcache.Client(["127.0.0.1:11211"])

        self.signal = AsyncSignal()
        self.add_read_event(self.signal)

        self.watcher = module(self)
        super(FluxMonitor, self).__init__()

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
