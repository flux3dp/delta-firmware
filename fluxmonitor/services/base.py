
from fluxmonitor.event_base import EventBase
from fluxmonitor.misc import AsyncSignal
import memcache


class ServiceBase(EventBase):
    def __init__(self, logger):
        self.self_test()
        super(ServiceBase, self).__init__()
        self.memcache = memcache.Client(["127.0.0.1:11211"])
        self.logger = logger

        self.signal = AsyncSignal()
        self.add_read_event(self.signal)

    def run(self):
        self.on_start()
        EventBase.run(self)
        self.on_shutdown()

    def each_loop(self):
        raise RuntimeError("each_loop not implement")

    def on_start(self):
        raise RuntimeError("start not implement")

    def shutdown(self, log):
        self.running = False
        self.signal.send()
        self.logger.info("Shutdown: %s" % log)

    def on_shutdown(self):
        raise RuntimeError("shutdown not implement")

    def self_test(self):
        import platform
        import os
        if platform.system().lower().startswith("linux"):
            if os.getuid() != 0:
                raise RuntimeError("""======== WARNING ========
We found fluxmonitord is not running as root. fluxmonitord can not
run without root privilege under linux.
""")