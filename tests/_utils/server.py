

from fluxmonitor.main import EventBase
from .memcache import MemcacheTestClient


class ServerSimulator(EventBase):
    def __init__(self):
        EventBase.__init__(self)
        self.cache = MemcacheTestClient()

    def each_loop(self):
        self.running = False
