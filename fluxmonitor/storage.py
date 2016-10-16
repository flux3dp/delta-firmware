
from random import choice
from shutil import rmtree
from time import time
import struct
import os

import sysv_ipc

from fluxmonitor.hal.usbmount import get_usbmount_hal
from fluxmonitor.err_codes import NOT_EXIST, BAD_PARAMS
from fluxmonitor.config import USERSPACE, general_config


class Storage(object):
    def __init__(self, *args):
        self.path = os.path.join(general_config["db"], *args)
        if not os.path.isdir(self.path):
            os.makedirs(self.path)

    def __setitem__(self, key, val):
        with self.open(key, "w") as f:
            f.write(val)

    def __getitem__(self, key):
        if self.exists(key):
            with self.open(key, "r") as f:
                return f.read()
        else:
            return None

    def __delitem__(self, key):
        if self.exists(key):
            self.unlink(key)

    def get_path(self, filename):
        return os.path.join(self.path, filename)

    def get_mtime(self, filename):
        return os.path.getmtime(self.get_path(filename))

    def list(self):
        return os.listdir(self.path)

    def exists(self, filename):
        return os.path.exists(self.get_path(filename))

    def remove(self, filename):
        os.remove(self.get_path(filename))

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


class Metadata(object):
    shm = None

    def __init__(self):
        self.storage = Storage("general", "meta")

        # Memory struct
        # 0 ~ 16 bytes: Control flags...
        #   0: nickname is loaded
        #   1: plate_correction is loaded
        #
        # 128 ~ 384: nickname, end with char \x00
        # 384 ~ 512: plate_correction (current user 96 bytes)
        # 1024 ~ 2048: Shared rsakey
        # 3072: Wifi status code
        # 3584 ~ 4096: Device status
        self.shm = sysv_ipc.SharedMemory(13000, sysv_ipc.IPC_CREAT,
                                         size=4096, init_character='\x00')

    def __del__(self):
        if self.shm:
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
                    except Exception:
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
            if isinstance(val, unicode):
                val = val.encode("utf8")
            f.write(val)
        self._cache_nickname(val)

    @property
    def broadcast(self):
        return self.storage["broadcast"]

    @broadcast.setter
    def broadcast(self, val):
        self.storage["broadcast"] = val

    @property
    def shared_der_rsakey(self):
        buf = self.shm.read(1024, 1024)
        bit, ts, l = struct.unpack("<BfH", buf[:7])
        if bit != 128:
            raise RuntimeError("RSA Key not ready")
        return buf[7:l + 7]

    @shared_der_rsakey.setter
    def shared_der_rsakey(self, val):
        h = struct.pack("<BfH", 128, time(), len(val))
        self.shm.write(h + val, 1024)

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
        return self.shm.read(64, 3584)

    @property
    def device_status_id(self):
        return struct.unpack("i", self.shm.read(4, 3592))[0]

    @property
    def format_device_status(self):
        buf = self.device_status
        timestemp, st_id, progress, head_type, err_label = \
            struct.unpack("dif16s32s", buf[:64])
        return {"timestemp": timestemp, "st_id": st_id, "progress": progress,
                "head_type": head_type, "err_label": err_label}

    def update_device_status(self, st_id, progress, head_type,
                             err_label=""):
        buf = struct.pack("dif16s32s", time(), st_id, progress, head_type,
                          err_label[:32])
        self.shm.write(buf, 3584)


class UserSpace(object):
    def __init__(self):
        self.filepool = os.path.realpath(USERSPACE)
        self.usbmount = get_usbmount_hal()

    def in_entry(self, entry, path):
        if entry == "SD":
            prefix = self.filepool
        elif entry == "USB":
            prefix = self.usbmount.get_entry()
            if not prefix:
                raise RuntimeError(NOT_EXIST, "BAD_NODE")
        else:
            raise RuntimeError(NOT_EXIST, "BAD_ENTRY")

        b = os.path.commonprefix([prefix, path])
        return b == prefix

    def get_path(self, _entry, _path, sd_only=False, require_file=False,
                 require_dir=False):
        if _entry == "SD":
            entry, path = self.filepool, _path
        elif _entry == "USB":
            if sd_only:
                raise RuntimeError(BAD_PARAMS, "USB_NOT_ACCESSABLE")
            filepool = self.usbmount.get_entry()
            if filepool:
                entry, path = filepool, _path
            else:
                raise RuntimeError(NOT_EXIST, "BAD_NODE")
        else:
            raise RuntimeError(NOT_EXIST, "BAD_ENTRY")

        abspath = os.path.realpath(os.path.join(entry, path))
        if not abspath.startswith(entry):
            raise RuntimeError(NOT_EXIST, "SECURITY_ISSUE")
        if require_file and (not os.path.isfile(abspath)):
            raise RuntimeError(NOT_EXIST, "NOT_FILE")
        if require_dir and (not os.path.isdir(abspath)):
            raise RuntimeError(NOT_EXIST, "NOT_DIR")
        return abspath

    def exist(self, entry, path):
        return os.path.exists(self.get_path(entry, path))

    def mv(self, entry, oldpath, newpath):
        os.rename(self.get_path(entry, oldpath),
                  self.get_path(entry, newpath))

    def rm(self, entry, path):
        try:
            os.remove(self.get_path(entry, path))
        except OSError:
            pass
