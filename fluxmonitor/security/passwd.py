
from hashlib import sha1
from hmac import HMAC
from time import time
import binascii

from fluxmonitor.security import _security
from fluxmonitor.storage import Storage
from .access_control import untrust_all
from .misc import randstr

_storage = Storage("security", "private")


def has_password():
    return _security.has_password()


def set_password(password, old_password):
    if validate_password(old_password):
        salt = randstr(8)
        pwdhash = HMAC(salt, password, sha1).hexdigest()
        with _storage.open("password", "w") as f:
            f.write(salt + ";" + pwdhash)
        untrust_all()

        return True
    else:
        return False


def validate_password(password):
    return _security.validate_password(password)


def validate_timestemp(memcache, timestemp, expire=60):
    t, salt = timestemp
    if abs(float(t) - time()) > 15:
        return False
    else:
        token = "ts:%s" % binascii.b2a_base64(salt)
        if memcache.get(token):
            return False
        else:
            assert memcache.set(token, "1", time=time() + expire)
            return True
