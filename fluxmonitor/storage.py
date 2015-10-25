
from random import choice
from shutil import rmtree
import struct
import os

import sysv_ipc

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
    def __init__(self):
        self.storage = Storage("general", "meta")

        # Memory struct
        # 0 ~ 16 bytes: Control flags...
        #   0: nickname is loaded
        #   1: plate_correction is loaded
        #
        # 128 ~ 384: nickname, end with char \x00
        # 384 ~ 512: plate_correction (current user 96 bytes)
        # 3072: Wifi status code
        # 3584 ~ 4096: Device status
        self.shm = sysv_ipc.SharedMemory(19851226, sysv_ipc.IPC_CREAT,
                                         size=4096, init_character='\x00')

    def __del__(self):
        self.shm.detach()
        self.shm = None

    @property
    def plate_correction(self):
        if ord(self.shm.read(1, 0)) & 64 == 64:
            buf = self.shm.read(96, 384)
            vals = struct.unpack("d" * 12, buf)
            return dict(zip("XYZABCIJKRDH", vals))
        else:
            if self.storage.exists("adjust"):
                with self.storage.open("adjust", "r") as f:
                    try:
                        vals = tuple((float(v) for v in f.read().split(" ")))
                        buf = struct.pack('d' * 12, *vals)
                        self.shm.write(buf, 384)

                        flag = chr(ord(self.shm.read(1, 0)) | 64)
                        self.shm.write(flag, 0)

                        return dict(zip("XYZABCIJKRDH", vals))
                    except Exception as e:
                        # Ignore error and return default
                        raise

        return {"X": 0, "Y": 0, "Z": 0, "A": 0, "B": 0, "C": 0,
                "I": 0, "J": 0, "K": 0, "R": 96.70, "D": 190, "H": 240}

    @plate_correction.setter
    def plate_correction(self, val):
        v = self.plate_correction
        v.update(val)

        vals = tuple((v[k] for k in "XYZABCIJKRDH"))
        with self.storage.open("adjust", "w") as f:
            f.write(" ".join("%.2f" % i for i in vals))
        buf = struct.pack('d' * 12, *vals)
        self.shm.write(buf, 384)

        flag = chr(ord(self.shm.read(1, 0)) | 64)
        self.shm.write(flag, 0)

    @property
    def nickname(self):
        if ord(self.shm.read(1, 0)) & 128 == 128:
            nickname = self.shm.read(256, 128)
            return nickname.rstrip('\x00')

        else:
            if self.storage.exists("nickname"):
                with self.storage.open("nickname", "rb") as f:
                    nickname = f.read()
                self._cache_nickname(nickname)
            else:
                nickname = ("Flux 3D Printer (%s)" %
                            choice(NICKNAMES)).encode()
                self.nickname = nickname

            return nickname

    @nickname.setter
    def nickname(self, val):
        with self.storage.open("nickname", "wb") as f:
            f.write(val)
        self._cache_nickname(val)

    def _cache_nickname(self, val):
        self.shm.write(val, 128)
        l = len(val)
        self.shm.write(b'\x00' * (256 - l), 128 + l)
        flag = chr(ord(self.shm.read(1, 0)) | 128)
        self.shm.write(flag, 0)

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

    @property
    def wifi_status(self):
        return ord(self.shm.read(1, 3072))

    @wifi_status.setter
    def wifi_status(self, val):
        self.shm.write(chr(val), 3072)

    @property
    def device_status(self):
        l = struct.unpack("H", self.shm.read(2, 3584))[0]
        return self.shm.read(l, 3586)

    @device_status.setter
    def device_status(self, val):
        # val struct:
        # (
        #   [Main Status, str label],
        #   [Minor Status, str label],
        #   [Head Type, str label],
        #   [Progress, float 0 ~ 1],
        # )
        prog = struct.pack("f", val[3])
        buf = val[0] + "\x00" + val[1] + "\x00" + val[2] + "\x00" + prog
        payload = struct.pack("H", len(buf)) + buf
        self.shm.write(payload, 3584)
