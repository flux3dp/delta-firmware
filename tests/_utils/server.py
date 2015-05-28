

from fluxmonitor.main import EventBase
from .memcache import MemcacheTestClient


class ServerSimulator(EventBase):
    def __init__(self):
        EventBase.__init__(self)
        self.cache = MemcacheTestClient()

    def do_loops(self):
        for obj in self.llist:
            obj.on_loop(self)

    def each_loop(self):
        self.running = False
