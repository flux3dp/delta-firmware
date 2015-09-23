
from random import choice
from shutil import rmtree
import os

from fluxmonitor.config import general_config


class Storage(object):
    def __init__(self, *args):
        self.path = os.path.join(general_config["db"], *args)
        if not os.path.isdir(self.path):
            os.makedirs(self.path)

    def get_path(self, filename):
        return os.path.join(self.path, filename)

    def get_mtime(self, filename):
        return os.path.getmtime(self.get_path(filename))

    def exists(self, filename):
        return os.path.exists(self.get_path(filename))

    def rmtree(self, path):
        p = self.get_path(path)
        if os.path.isdir(p):
            rmtree(p)

    def unlink(self, filename):
        os.unlink(self.get_path(filename))

    def open(self, filename, *args):
        return open(self.get_path(filename), *args)

    def readall(self, filename):
        if self.exists(filename):
            with self.open(filename, "rb") as f:
                return f.read()
        else:
            return None


NICKNAMES = ["Apple", "Apricot", "Avocado", "Banana", "Bilberry", "Blackberry",
             "Blackcurrant", "Blueberry", "Boysenberry", "Cantaloupe",
             "Currant", "Cherry", "Cherimoya", "Cloudberry", "Coconut",
             "Cranberry", "Damson", "Date", "Dragonfruit", "Durian",
             "Elderberry", "Feijoa", "Fig", "Goji berry", "Gooseberry",
             "Grape", "Raisin", "Grapefruit", "Guava", "Huckleberry",
             "Jackfruit", "Jambul", "Jujube", "Kiwi fruit", "Kumquat", "Lemon",
             "Lime", "Loquat", "Lychee", "Mango", "Marion berry", "Melon",
             "Cantaloupe", "Honeydew", "Watermelon", "Rock melon",
             "Miracle fruit", "Mulberry", "Nectarine", "Olive", "Orange",
             "Blood Orange", "Clementine", "Mandarine", "Tangerine", "Papaya",
             "Passionfruit", "Peach", "Pear", "Williams pear", "Bartlett pear",
             "Persimmon", "Physalis", "Pineapple", "Pomegranate", "Pomelo",
             "Purple Mangosteen", "Quince", "Raspberry", "Salmon berry",
             "Black raspberry", "Rambutan", "Redcurrant", "Salal berry",
             "Satsuma", "Star fruit", "Strawberry", "Tamarillo", "Ugli fruit"]


class CommonMetadata(object):
    _nickname = None
    _nickname_mtime = None

    def __init__(self):
        self.storage = Storage("general", "meta")

    def get_nickname(self):
        if not self.storage.exists("nickname"):
            self.set_nickname("Flux 3D Printer (%s)" % choice(NICKNAMES))

        mtime = self.storage.get_mtime("nickname")
        if mtime != self._nickname_mtime:
            with self.storage.open("nickname", "r") as f:
                self._nickname = f.read()
                self._nickname_mtime = mtime

        return self._nickname

    def set_nickname(self, name):
        with self.storage.open("nickname", "w") as f:
            f.write(name)

    @property
    def play_bufsize(self):
        try:
            with self.storage.open("play_bufsize", "r") as f:
                val = int(f.read())
                return val if val >= 1 else 1
        except Exception:
            return 2

    @play_bufsize.setter
    def play_bufsize(self, val):
        with self.storage.open("play_bufsize", "w") as f:
            return f.write(str(val))
