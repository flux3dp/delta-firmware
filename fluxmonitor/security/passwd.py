
from hashlib import sha1
from hmac import HMAC

from fluxmonitor.storage import Storage
from .access_control import untrust_all
from .misc import randstr

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
