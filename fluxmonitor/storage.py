
from random import choice
from shutil import rmtree
import msgpack
import struct
import os

import sysv_ipc

from fluxmonitor.misc.systime import systime as time
from fluxmonitor.err_codes import NOT_EXIST, BAD_PARAMS
from fluxmonitor.config import DEFAULT_R, DEFAULT_H


class Storage(object):
    def __init__(self, *args):
        from fluxmonitor.config import general_config
        self.path = os.path.join(general_config["db"], *args)
        if not os.path.isdir(self.path):
            os.makedirs(self.path)

    def __contains__(self, key):
        return os.path.exists(self.get_path(key))

    def __setitem__(self, key, val):
        with self.open(key, "w") as f:
            f.write(val)

    def __getitem__(self, key):
        p = self.get_path(key)
        if os.path.isfile(p):
            with self.open(p, "r") as f:
                return f.read()
        else:
            return None

    def __delitem__(self, key):
        p = self.get_path(key)
        if os.path.isdir(p):
            rmtree(p)
        elif os.path.isfile(p) or os.path.islink(p):
            os.unlink(p)
        elif os.path.exists(p):
            raise SystemError("OPERATION_ERROR", "FS_RM_ERROR")

    def get_path(self, filename):
        return os.path.join(self.path, filename)

    def get_mtime(self, filename):
        return os.path.getmtime(self.get_path(filename))

    def list(self):
        return os.listdir(self.path)

    def exists(self, filename):
        return filename in self

    def remove(self, filename):
        del self[filename]

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


class Preference(object):
    _i = None

    @classmethod
    def instance(cls):
        if cls._i is None:
            cls._i = cls()
        return cls._i

    def __init__(self):
        self._storage = Storage("general", "meta")

    @property
    def nickname(self):
        if self._storage.exists("nickname"):
            with self._storage.open("nickname", "rb") as f:
                return f.read()
        else:
            nickname = ("Flux 3D Printer (%s)" %
                        choice(NICKNAMES)).encode()
            with self._storage.open("nickname", "wb") as f:
                f.write(nickname)
        return nickname

    @nickname.setter
    def nickname(self, val):
        if isinstance(val, unicode):
            val = val.encode("utf8")
        else:
            try:
                val.decode("utf8")
            except UnicodeDecodeError:
                raise RuntimeError(BAD_PARAMS)

        if len(val) > 128:
            raise RuntimeError(BAD_PARAMS)

        with self._storage.open("nickname", "wb") as f:
            f.write(val)

    @property
    def leveling(self):
        if self._storage.exists("leveling"):
            with self._storage.open("leveling", "r") as f:
                try:
                    vals = tuple((float(v) for v in f.read().split(" ")))
                    return dict(zip("XYZABCIJKRDH", vals))
                except Exception:
                    # Ignore error and return default
                    pass

        return {"X": 0, "Y": 0, "Z": 0, "A": 0, "B": 0, "C": 0,
                "I": 0, "J": 0, "K": 0, "R": DEFAULT_R, "D": 189.75,
                "H": DEFAULT_H}

    @leveling.setter
    def leveling(self, val):
        v = self.leveling
        v.update(val)

        vals = tuple((v[k] for k in "XYZABCIJKRDH"))
        with self._storage.open("leveling", "w") as f:
            f.write(" ".join("%.4f" % i for i in vals))

    plate_correction = leveling

    @property
    def backlash(self):
        if self._storage.exists("backlash"):
            with self._storage.open("backlash", "r") as f:
                try:
                    vals = tuple((float(v) for v in f.read().split(" ")))
                    return dict(zip("ABC", vals))
                except Exception:
                    # Ignore error and return default
                    pass

        return {"A": 10, "B": 10, "C": 10}

    @backlash.setter
    def backlash(self, val):
        v = self.backlash
        v.update(val)

        vals = tuple((v[k] for k in "ABC"))
        with self._storage.open("backlash", "w") as f:
            f.write(" ".join("%.4f" % i for i in vals))

    @property
    def broadcast(self):
        return self._storage["broadcast"]

    @broadcast.setter
    def broadcast(self, val):
        self._storage["broadcast"] = val

    @broadcast.deleter
    def broadcast(self):
        del self._storage["broadcast"]

    @property
    def enable_cloud(self):
        return self._storage["enable_cloud"]

    @enable_cloud.setter
    def enable_cloud(self, val):
        self._storage["enable_cloud"] = val

    @enable_cloud.deleter
    def enable_cloud(self):
        del self._storage["enable_cloud"]


class Metadata(object):
    shm = None
    _mversion = 0

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Memory struct
        # 0: Control flags...
        # 1: Metadata Version
        # 2: Toolhead mode, 0: default, 1: delay 5v switch off
        #
        # 128 ~ 384: nickname, end with char \x00
        # 1024 ~ 2048: Shared rsakey
        # 2048 ~ 2176: Cloud Status (128)
        # 2176 ~ 2208: Cloud Hash (32)
        # 3072: Wifi status code
        # # 3576 ~ 3584: Task time cost (8, float)
        # 3584 ~ 4096: Device status

        self.shm = sysv_ipc.SharedMemory(13001, sysv_ipc.IPC_CREAT,
                                         size=4096, init_character='\x00')
        self.pref = Preference.instance()

    def __del__(self):
        if self.shm:
            self.shm.detach()
            self.shm = None

    def verify_mversion(self):
        # Return True if mversion is not change.
        if self._mversion != self.mversion:
            self._mversion = self.mversion
            return False
        else:
            return True

    @property
    def mversion(self):
        return ord(self.shm.read(1, 1))

    def _add_mversion(self):
        self.shm.write(chr((ord(self.shm.read(1, 1)) + 1) % 256), 1)

    @property
    def nickname(self):
        size = ord(self.shm.read(1, 128))
        if size == 0:
            nickname = self.pref.nickname
            self.shm.write(struct.pack("B255s", len(nickname), nickname), 128)
        else:
            nickname = self.shm.read(size, 129)
        return nickname

    @nickname.setter
    def nickname(self, val):
        self.pref.nickname = val
        val = self.pref.nickname
        self.shm.write(struct.pack("B255s", len(val), val), 128)
        self._add_mversion()

    @property
    def delay_toolhead_poweroff(self):
        return self.shm.read(1, 2)

    @delay_toolhead_poweroff.setter
    def delay_toolhead_poweroff(self, val):
        self.shm.write(val[:1], 2)

    @property
    def broadcast(self):
        return self.pref.broadcast

    @broadcast.setter
    def broadcast(self, val):
        self.pref.broadcast = val
        self._add_mversion()

    @property
    def enable_cloud(self):
        return self.pref.enable_cloud

    @enable_cloud.setter
    def enable_cloud(self, val):
        self.pref.enable_cloud = val
        self._add_mversion()

    @enable_cloud.deleter
    def enable_cloud(self):
        del self.pref.enable_cloud
        self._add_mversion()

    @property
    def cloud_status(self):
        buf = self.shm.read(128, 2048)
        l = ord(buf[0])
        if l > 0:
            return msgpack.unpackb(buf[1:ord(buf[0]) + 1], use_list=False)
        else:
            return None

    @cloud_status.setter
    def cloud_status(self, val):
        buf = msgpack.packb(val)
        if len(buf) > 127:
            raise SystemError("%s is too large to store", val)
        self.shm.write(chr(len(buf)) + buf, 2048)

    @property
    def cloud_hash(self):
        return self.shm.read(32, 2176)

    @cloud_hash.setter
    def cloud_hash(self, val):
        self.shm.write(val[:32], 2176)

    @property
    def wifi_status(self):
        return ord(self.shm.read(1, 3072))

    @wifi_status.setter
    def wifi_status(self, val):
        self.shm.write(chr(val), 3072)

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

    @property
    def device_status(self):
        return self.shm.read(64, 3584)

    @property
    def device_status_id(self):
        return struct.unpack("i", self.shm.read(4, 3592))[0]

    @property
    def format_device_status(self):
        buf = self.device_status
        timestamp, st_id, progress, head_type, err_label = \
            struct.unpack("dif16s32s", buf[:64])
        ip_addr = self.ip_cache
        return {"timestamp": timestamp, "st_id": st_id, "progress": progress,
                "head_type": head_type.rstrip('\x00'),
                "err_label": err_label.rstrip('\x00'),
                "ip_addr": ip_addr}

    def update_device_status(self, st_id, progress, head_type,
                             err_label=""):
        if isinstance(head_type, unicode):
            head_type = head_type.encode()
        if isinstance(err_label, unicode):
            err_label = err_label.encode()
        buf = struct.pack("dif16s32s", time(), st_id, progress, head_type,
                          err_label[:32])
        self.shm.write(buf, 3584)

    @property
    def ip_cache(self):
        return self.shm.read(64, 3700).decode()

    @ip_cache.setter
    def ip_cache(self, val):
        self.shm.write(val[:63], 3700)
    


class UserSpace(object):
    def __init__(self):
        from fluxmonitor.hal.usbmount import get_usbmount_hal
        from fluxmonitor.config import USERSPACE
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


metadata = Metadata()
