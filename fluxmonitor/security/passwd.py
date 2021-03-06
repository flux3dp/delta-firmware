
from hashlib import sha1
from hmac import HMAC

from .misc import randstr


def get_storage():
    from fluxmonitor.storage import Storage
    return Storage("security", "private")


def hash_password(salt, paragraph):
    return HMAC(salt, paragraph, sha1).digest()


def has_password():
    return get_storage().exists("password")


def set_password(password):
    if password:
        salt = randstr(8)
        pwdhash = HMAC(salt, password, sha1).hexdigest()
        with get_storage().open("password", "w") as f:
            f.write(salt + ";" + pwdhash)
    else:
        if has_password():
            get_storage().remove("password")


def validate_password(password):
    if has_password():
        with get_storage().open("password", "r") as f:
            salt, pwdhash = f.read().split(";")
            inputhash = HMAC(salt, password, sha1).hexdigest()
            return pwdhash == inputhash
    else:
        return True
