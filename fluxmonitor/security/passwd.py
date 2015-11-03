
from hashlib import sha1
from hmac import HMAC
from time import time
import binascii

from fluxmonitor.security import _security
from fluxmonitor.storage import Storage
from .access_control import untrust_all
from .misc import randstr

__ts_salt = []
__ts_time = []
_storage = Storage("security", "private")


def has_password():
    return _security.has_password()


def validate_and_set_password(password, old_password):
    if validate_password(old_password):
        _set_password(password)
        untrust_all()

        return True
    else:
        return False


def set_password(password):
    salt = randstr(8)
    pwdhash = HMAC(salt, password, sha1).hexdigest()
    with _storage.open("password", "w") as f:
        f.write(salt + ";" + pwdhash)


def validate_password(password):
    return _security.validate_password(password)


def validate_timestemp(timestemp, now=None):
    global __ts_time, __ts_salt
    if now is None:
        now = time()
    t, salt = timestemp

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


def reset_timestemp():
    global __ts_time, __ts_salt
    __ts_salt = []
    __ts_time = []
