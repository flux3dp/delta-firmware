

class WatcherBase(object):
    def __init__(self, server, logger):
        self.server = server
        self.memcache = server.cache
        self.logger = logger

    def each_loop(self):
        raise RuntimeError("each_loop not implement")

    def start(self):
        raise RuntimeError("start not implement")

    def shutdown(self):
        raise RuntimeError("shutdown not implement")
