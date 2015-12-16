
import weakref

from setproctitle import setproctitle
import pyev


class ServiceBase(object):
    def __init__(self, logger):
        setproctitle("flux: %s" % self.__class__.__name__)
        self.self_test()

        super(ServiceBase, self).__init__()
        self.logger = logger

        self.loop = loop = pyev.default_loop()
        loop.data = weakref.proxy(self)

        self.shutdown_signal = loop.async(lambda w, r: w.loop.stop())
        self.shutdown_signal.start()

    def run(self):
        self.on_start()
        self.loop.start()
        self.on_shutdown()

    def each_loop(self):
        raise RuntimeError("each_loop not implement")

    def on_start(self):
        raise RuntimeError("start not implement")

    def shutdown(self, log):
        self.logger.info("Shutdown: %s" % log)
        self.shutdown_signal.send()

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
