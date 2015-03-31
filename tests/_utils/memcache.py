
from time import time


class MemcacheTestClient(object):
    def __init__(self):
        self.data = {}

    def get(self, key):
        val, ts = self.data.get(key, (None, 0))
        if time() <= ts:
            return val

    def set(self, key, value, time=None):
        self.data[key] = (str(value), time)
        return "ok"

    def delete(self, key):
        self.data.pop(key, None)

    def erase(self):
        self.data = {}
