
from fluxmonitor.security._security import RSAObject, is_rsakey
from hashlib import sha1
import json
import os
import re

from fluxmonitor.storage import Storage

_safe_value = lambda val: re.match("^[a-zA-Z0-9]+$", val) is not None  # noqa
ADMIN_KEY = "A"
USER_KEY = "U"
RE_ACCESS_ID = re.compile(r'^[0-9a-f]{40}$')


class AccessControl(object):
    _default = None

    @classmethod
    def instance(cls):
        if not cls._default:
            cls._default = cls()
        return cls._default

    def __init__(self, storage=None):
        self.storage = storage if storage else Storage("security", "pub")

    def get_keyobj(self, pem=None, der=None, access_id=None):
        if access_id:
            if _safe_value(access_id) and self.storage.exists(access_id):
                buf = self.storage.readall(access_id)
                try:
                    if buf.startswith("-----BEGIN "):
                        return RSAObject(pem=buf)
                    else:
                        return RSAObject(der=buf)
                except (RuntimeError, TypeError):
                    self.storage.unlink(access_id)
                    return None
            else:
                return None

        try:
            return RSAObject(pem=pem, der=der)
        except (TypeError, ValueError, RuntimeError):
            return None

    def get_access_id(self, pem=None, der=None, keyobj=None):
        if not keyobj:
            keyobj = self.get_keyobj(pem=pem, der=der)
            if not keyobj:
                raise Exception("key error")
        return sha1(keyobj.export_pubkey_der()).hexdigest()

    def add(self, keyobj, **kw):
        access_id = get_access_id(keyobj=keyobj)

        with self.storage.open(access_id, "w") as f:
            f.write(keyobj.export_pubkey_pem())
            os.fsync(f.fileno())

        meta = {
            "label": kw.get("label", None),
            "type": kw.get("type", USER_KEY)
        }
        if meta["type"] not in (USER_KEY, ADMIN_KEY):
            meta["type"] = USER_KEY
        with self.storage.open(access_id + ".meta", "w") as f:
            json.dump(meta, f)
            os.fsync(f.fileno())
        return access_id

    def get_metadata(self, access_id):
        try:
            with self.storage.open(access_id + ".meta") as f:
                return json.load(f)
        except (IOError, ValueError):
            return {}

    def list(self):
        for name in self.storage.list():
            if RE_ACCESS_ID.match(name):
                meta = self.get_metadata(name)
                meta["access_id"] = name
                yield meta

    def is_trusted(self, access_id=None, pem=None, der=None, keyobj=None):
        if not access_id:
            access_id = self.get_access_id(pem=pem, der=der, keyobj=keyobj)

        if access_id:
            return self.storage.exists(access_id)
        else:
            return False

    def remove(self, access_id):
        if self.storage.exists(access_id):
            self.storage.remove(access_id)

            if self.storage.exists(access_id + ".meta"):
                self.storage.remove(access_id + ".meta")

            return True
        else:
            return False

    def remove_all(self):
        for meta in tuple(self.list()):
            self.remove(meta["access_id"])

    def is_rsakey(self, pem=None, der=None):
        return is_rsakey(pem, der)

_access_control = AccessControl.instance


def get_keyobj(pem=None, der=None, access_id=None):
    return _access_control.get_keyobj(pem=pem, der=der, access_id=access_id)


def get_access_id(pem=None, der=None, keyobj=None):
    return _access_control.get_access_id(pem=pem, der=der, keyobj=keyobj)


def is_trusted_remote(access_id=None, pem=None, der=None, keyobj=None):
    return _access_control.is_trusted(
        access_id=access_id, pem=pem, der=der, keyobj=keyobj)


def add_trusted_keyobj(keyobj, label=None):
    return _access_control.add(keyobj, label=label)


def untrust_all():
    _access_control.remove_all()
