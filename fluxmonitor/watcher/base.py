
import threading
import select

from fluxmonitor.misc import AsyncSignal as _AsyncSignal


class AsyncSignal(_AsyncSignal):
    def on_read(self):
        self.recv()


class WatcherBase(threading.Thread):
    POLL_TIMEOUT = 5.0

    def __init__(self, logger, memcache):
        self.memcache = memcache
        self.logger = logger
        self.__shutdown_sig = AsyncSignal()

        self.rlist = [self.__shutdown_sig]

        super(WatcherBase, self).__init__()
        self.setDaemon(True)

    def each_loop(self):
        pass

    def run(self):
        self.running = True

        while self.running:
            rlist, wlist, xlist = select.select(self.rlist,
                                                (),
                                                (),
                                                self.POLL_TIMEOUT)
            for r in rlist:
                try:
                    r.on_read()
                except Exception:
                    self.logger.exception("Unhandle error")

                try:
                    self.each_loop()
                except Exception:
                    self.logger.exception("Unhandle error")

    def shutdown(self, log=None):
        self.running = False
        self.__shutdown_sig.send()
        self.logger.info("Shutdown: %s" % log)
