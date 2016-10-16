
from hashlib import sha1
from hmac import HMAC
from time import time

from fluxmonitor.storage import Storage
from .access_control import untrust_all
from .misc import randstr

__ts_salt = []
__ts_time = []
_storage = Storage("security", "private")


def hash_password(salt, paragraph):
    return HMAC(salt, paragraph, sha1).digest()


def has_password():
    return _storage.exists("password")


def validate_and_set_password(password, old_password, reset_acl=True):
    if validate_password(old_password):
        set_password(password)
        if reset_acl:
            untrust_all()

        return True
    else:
        return False


def set_password(password):
    if password:
        salt = randstr(8)
        pwdhash = HMAC(salt, password, sha1).hexdigest()
        with _storage.open("password", "w") as f:
            f.write(salt + ";" + pwdhash)
    else:
        if has_password():
            _storage.remove("password")


def validate_password(password):
    if has_password():
        with _storage.open("password", "r") as f:
            salt, pwdhash = f.read().split(";")
            inputhash = HMAC(salt, password, sha1).hexdigest()
            return pwdhash == inputhash
    else:
        return True


def validate_timestamp(timestamp, now=None):
    global __ts_time, __ts_salt
    if now is None:
        now = time()
    t, salt = timestamp

    if abs(t - now) > 15:
        return False
    else:
        while __ts_time and __ts_time[0] < now:
            __ts_salt.pop()
            __ts_time.pop()

        if salt in __ts_salt:
            return False
        else:
            if __ts_time and now < __ts_time[-1]:
                now = __ts_time[-1]

            __ts_salt.append(salt)
            __ts_time.append(now + 31)
            return True


def reset_timestamp():
    global __ts_time, __ts_salt
    __ts_salt = []
    __ts_time = []
