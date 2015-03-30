
from random import choice
from shutil import rmtree
from hashlib import sha1
from io import BytesIO
from hmac import HMAC
from time import time
import logging
import os
import re

logger = logging.getLogger(__name__)

from Crypto.Signature import PKCS1_v1_5
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Hash import SHA as CryptoSHA

from fluxmonitor.config import general_config

KEYLENGTH = general_config["keylength"]
STR_BASE = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

_safe_value = lambda val: re.match("^[a-zA-Z0-9]+$", val) != None
_create_salt = lambda size=8: "".join((choice(STR_BASE) for i in range(size)))


def is_rsakey(pem):
    try:
        RSA.importKey(pem)
        return True
    except (TypeError, ValueError, IndexError):
        return False

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

    chip = PKCS1_OAEP.new(key)
    size = ((key.size() + 1) / 8) - 42
    in_buf = BytesIO(message)
    out_buf = BytesIO()

    buf = in_buf.read(size)
    while buf:
        out_buf.write(chip.encrypt(buf))
        buf = in_buf.read(size)

    return out_buf.getvalue()

def decrypt_msg(message, pem=None):
    if pem:
        key = RSA.importKey(pem)
    else:
        key = _get_private_key()

    chip = PKCS1_OAEP.new(key)
    size = (key.size() + 1) / 8
    in_buf = BytesIO(message)
    out_buf = BytesIO()

    buf = in_buf.read(size)
    while buf:
        try:
            out_buf.write(chip.decrypt(buf))
        except ValueError:
            import IPython
            IPython.embed()
        buf = in_buf.read(size)

    return out_buf.getvalue()

def sign(message, pem=None):
    if pem:
        key = RSA.importKey(pem)
    else:
        key = _get_private_key()
    chip = PKCS1_v1_5.new(key)
    return chip.sign(CryptoSHA.new(message))

def verify_signature(message, signature, access_id):
    pem = _get_remote_pubkey(access_id)
    if pem:
        key = RSA.importKey(pem)
        chip = PKCS1_v1_5.new(key)
        return chip.verify(CryptoSHA.new(message), signature)
    else:
        return False

def add_trust_publickey(pem):
    key = RSA.importKey(pem)
    access_id = get_access_id(key=key)
    filename = _get_path("pub", access_id)

    with open(filename, "w") as f:
        f.write(key.exportKey("PEM"))
    return access_id

def is_trusted_access_id(access_id):
    filename = _get_path("pub", access_id)
    return os.path.isfile(filename)

def is_trusted_publickey(pem):
    key = RSA.importKey(pem)
    access_id = get_access_id(key=key)
    return is_trusted_access_id(access_id)

def get_access_id(pem=None, key=None):
    if not key:
        key = RSA.importKey(pem)
    return sha1(key.exportKey("PEM")).hexdigest()

def has_password():
    return os.path.isfile(_get_password_filename())

def set_password(memcache, password, old_password, timestemp=None):
    if validate_password(memcache, old_password):
        salt = _create_salt(8)
        pwdhash = HMAC(salt, password, sha1).hexdigest()
        with open(_get_password_filename(), "w") as f:
            f.write(salt + ";" + pwdhash)
        pubdir = _get_path("pub")
        if os.path.isdir(pubdir):
            rmtree(_get_path("pub"))
        return True
    else:
        return False

def validate_password(memcache, password, timestemp=None):
    if timestemp and not validate_timestemp(memcache, timestemp):
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

def _get_remote_pubkey(access_id):
    if _safe_value(access_id):
        fn = _get_path("pub", access_id)
        if os.path.isfile(fn):
             with open(fn, "r") as f:
                 return f.read()

def _get_password_filename():
    return _get_path("private", "password")

def _get_key_filename():
    return _get_path("private", "key.pem")

def _get_path(*path):
    basedir = os.path.join(general_config["db"], "security", *(path[:-1]))
    if not os.path.isdir(basedir):
        os.makedirs(basedir)
    return os.path.join(basedir, path[-1])
