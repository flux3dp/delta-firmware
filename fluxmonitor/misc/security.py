
from hashlib import md5, sha1
from random import choice
from hmac import HMAC
from time import time
import logging
import os
import re

logger = logging.getLogger(__name__)

from Crypto.PublicKey import RSA

from fluxmonitor.config import general_config

KEYLENGTH = 4096
STR_BASE = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

_safe_value = lambda val: re.match("^[a-zA-Z0-9]+$", val) != None
_create_salt = lambda size=8: "".join((choice(STR_BASE) for i in range(size)))
_get_path = lambda *path: os.path.join(general_config["db"], "security", *path)


def get_publickey():
    private_key = _get_private_key()
    return private_key.publickey().exportKey('PEM')

def encrypt_msg(message, access_id=None):
    if access_id:
        pem = _get_remote_pubkey(access_id)
        if pem:
            key = RSA.importKey(pem)
        else:
            return b""
    else:
        key = _get_private_key()
    return key.encrypt(message, 0)[0]

def decrypt_msg(message):
    key = _get_private_key()
    return key.decrypt(message)

def issue_access_id(pem):
    return _set_remote_pubkey(pem)

def has_password():
    return os.path.isfile(_get_password_filename())

def set_password(memcache, password, old_password, timestemp):
    if validate_password(memcache, old_password, timestemp):
        salt = _create_salt(8)
        pwdhash = HMAC(salt, password, sha1).hexdigest()
        with open(_get_password_filename(), "w") as f:
            f.write(salt + ";" + pwdhash)
        return True
    else:
        return False

def validate_password(memcache, password, timestemp):
    if not validate_timestemp(memcache, timestemp):
        return False
    if has_password():
        with open(_get_password_filename(), "r") as f:
            salt, pwdhash = f.read().split(";")
            inputhash = HMAC(salt, password, sha1).hexdigest()
            return pwdhash == inputhash
    else:
        return True

def validate_timestemp(memcache, timestemp, expire=300):
    if abs(float(timestemp) - time()) > 15:
        return False
    else:
        token = "timestemp-%s" % timestemp
        if memcache.get(token):
            return False
        else:
            assert memcache.set(token, "1", time=time() + expire)
            return True

def _get_private_key():
    filename = _get_key_filename()
    if not os.path.isfile(filename):
        _create_key(filename)
        logger.info("Private key created at: %s" % filename)

    with open(filename, "r") as f:
        return RSA.importKey(f.read())

def _create_key(filename):
    key = RSA.generate(KEYLENGTH)
    with open(filename, "w") as f:
        f.write(key.exportKey('PEM'))

def _set_remote_pubkey(pem):
    basedir = _get_path("pub")
    if not os.path.isdir(basedir):
        os.makedirs(basedir)
    access_id = md5(pem).hexdigest()
    filename = _get_path("pub", access_id)
    with open(filename, "w") as f:
        f.write(pem)
    return access_id

def _get_remote_pubkey(access_id):
    if _safe_value(access_id):
        fn = _get_path("pub", access_id)
        if os.path.isfile(fn):
             with open(fn, "r") as f:
                 return f.read()

def _get_password_filename():
    return _get_path("password")

def _get_key_filename():
    basedir = _get_path("private")
    if not os.path.isdir(basedir):
        os.makedirs(basedir)

    return os.path.join(basedir, "key.pem")


