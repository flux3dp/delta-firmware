
from random import choice
from shutil import rmtree
from hashlib import sha1
from hmac import HMAC
from time import time
import binascii
import logging
import os
import re

logger = logging.getLogger(__name__)

from fluxmonitor.misc._security import RSAObject
from fluxmonitor.config import general_config

KEYLENGTH = general_config["keylength"]
STR_BASE = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_UINT64 = (2 ** 64) - 1


_safe_value = lambda val: re.match("^[a-zA-Z0-9]+$", val) is not None


def get_serial():
    pubpem = get_private_key().export_pubkey_pem()
    dig = sha1(pubpem).digest()[:16]
    return binascii.b2a_hex(dig)


def randstr(length=8):
    return "".join((choice(STR_BASE) for i in range(length)))


def randbytes(length=128):
    with open("/dev/urandom") as f:
        return f.read(length)


def get_private_key():
    filename = _get_key_filename()
    if os.path.isfile(filename):
        try:
            with open(filename, "r") as f:
                return RSAObject(pem=f.read())
        except RuntimeError:
            pass

    rsaobj = RSAObject(keylength=KEYLENGTH)
    pem = rsaobj.export_pem()
    with open(filename, "w") as f:
        f.write(pem)
    logger.info("Private key created at: %s" % filename)

    return rsaobj


def get_keyobj(pem=None, der=None, access_id=None):
    if access_id and _safe_value(access_id):
        fn = _get_path("pub", access_id)
        if os.path.isfile(fn):
            with open(fn, "r") as f:
                buf = f.read()
                try:
                    if buf.startswith("-----BEGIN "):
                        return RSAObject(pem=buf)
                    else:
                        return RSAObject(der=buf)
                except RuntimeError:
                    os.unlink(fn)
                    raise

    try:
        return RSAObject(pem=pem, der=der)
    except (TypeError, ValueError, RuntimeError):
        return None


def is_rsakey(pem=None, der=None):
    if not pem and not der:
        return False
    try:
        RSAObject(pem=pem, der=der)
        return True
    except (RuntimeError, TypeError):
        return False


def add_trusted_keyobj(keyobj):
    access_id = get_access_id(keyobj=keyobj)
    filename = _get_path("pub", access_id)

    with open(filename, "w") as f:
        f.write(keyobj.export_pem())
    return access_id


def is_trusted_remote(access_id=None, pem=None, der=None, keyobj=None):
    if not access_id:
        access_id = get_access_id(pem=pem, der=der, keyobj=keyobj)

    if access_id:
        return os.path.isfile(_get_path("pub", access_id))
    else:
        return False


def get_access_id(pem=None, der=None, keyobj=None):
    if not keyobj:
        keyobj = get_keyobj(pem=pem, der=der)
        if not keyobj:
            return ""
    return sha1(keyobj.export_pem()).hexdigest()


def has_password():
    return os.path.isfile(_get_password_filename())


def set_password(memcache, password, old_password):
    if validate_password(memcache, old_password):
        salt = randstr(8)
        pwdhash = HMAC(salt, password, sha1).hexdigest()
        with open(_get_password_filename(), "w") as f:
            f.write(salt + ";" + pwdhash)
        pubdir = _get_path("pub")
        if os.path.isdir(pubdir):
            rmtree(_get_path("pub"))
        return True
    else:
        return False


def validate_password(memcache, password):
    if has_password():
        with open(_get_password_filename(), "r") as f:
            salt, pwdhash = f.read().split(";")
            inputhash = HMAC(salt, password, sha1).hexdigest()
            return pwdhash == inputhash
    else:
        return True


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


def _set_password(password):
    salt = randstr(8)
    pwdhash = HMAC(salt, password, sha1).hexdigest()
    with open(_get_password_filename(), "w") as f:
        f.write(salt + ";" + pwdhash)
    pubdir = _get_path("pub")
    if os.path.isdir(pubdir):
        rmtree(_get_path("pub"))
    return True


def _get_password_filename():
    return _get_path("private", "password")


def _get_key_filename():
    return _get_path("private", "key.pem")


def _get_path(*path):
    basedir = os.path.join(general_config["db"], "security", *(path[:-1]))
    if not os.path.isdir(basedir):
        os.makedirs(basedir)
    return os.path.join(basedir, path[-1])
