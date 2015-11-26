
from time import time


def update_time(fn):
    def wrap(self, *args, **kw):
        self._at = time()
        return fn(self, *args, **kw)
    return wrap


def time_since_update(instance):
    return time() - instance._at
