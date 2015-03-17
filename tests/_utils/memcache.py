

class MemcacheTestClient(object):
    data = {}

    def __init__(self):
        pass

    def get(self, key):
        self.data.get(key)

    def set(self, key, value):
        self.data[key] = str(value)

