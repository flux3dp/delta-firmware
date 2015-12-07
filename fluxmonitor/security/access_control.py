
from fluxmonitor.security._security import RSAObject
from hashlib import sha1
import re

from fluxmonitor.storage import Storage
from fluxmonitor.security import _security

_storage = Storage("security", "pub")
_safe_value = lambda val: re.match("^[a-zA-Z0-9]+$", val) is not None


def get_keyobj(pem=None, der=None, access_id=None):
    if access_id and _safe_value(access_id):
        if _storage.exists(access_id):
            with _storage.open(access_id, "r") as f:
                buf = f.read()
                try:
                    if buf.startswith("-----BEGIN "):
                        return RSAObject(pem=buf)
                    else:
                        return RSAObject(der=buf)
                except RuntimeError:
                    _storage.unlink(access_id)
                    raise

    try:
        return RSAObject(pem=pem, der=der)
    except (TypeError, ValueError, RuntimeError):
        return None


def get_access_id(pem=None, der=None, keyobj=None):
    if not keyobj:
        keyobj = get_keyobj(pem=pem, der=der)
        if not keyobj:
            raise Exception("key error")
    return sha1(keyobj.export_pubkey_der()).hexdigest()


def is_trusted_remote(access_id=None, pem=None, der=None, keyobj=None):
    if not access_id:
        access_id = get_access_id(pem=pem, der=der, keyobj=keyobj)

    if access_id:
        return _storage.exists(access_id)
    else:
        return False


def add_trusted_keyobj(keyobj):
    access_id = get_access_id(keyobj=keyobj)

    with _storage.open(access_id, "w") as f:
        f.write(keyobj.export_pubkey_pem())
    return access_id


def is_rsakey(pem=None, der=None):
    return _security.is_rsakey(pem, der)


def untrust_all():
    global _storage
    _storage.rmtree("")
    _storage = Storage("security", "pub")
