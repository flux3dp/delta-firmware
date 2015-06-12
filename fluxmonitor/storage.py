
import os

from fluxmonitor.config import general_config


class Storage(object):
    def __init__(self, *args):
        self.path = os.path.join(general_config["db"], *args)
        if not os.path.isdir(self.path):
            os.makedirs(self.path)

    def get_path(self, filename):
        return os.path.join(self.path, filename)

    def exists(self, filename):
        return os.path.exists(self.get_path(filename))

    def open(self, filename, *args):
        return open(self.get_path(filename), *args)
