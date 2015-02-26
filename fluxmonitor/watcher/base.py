
import threading

class WatcherBase(threading.Thread):
    def __init__(self):
        super(WatcherBase, self).__init__()
        self.setDaemon(True)

    def run(self):
        raise RuntimeError("Override Me")

    def shutdown(self, log=None):
        raise RuntimeError("Override Me")

