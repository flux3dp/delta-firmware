
from hashlib import sha1
from uuid import UUID
import binascii
import logging

from fluxmonitor.security._security import RSAObject
from fluxmonitor.config import general_config
from fluxmonitor.storage import Storage

KEYNAME = "key.pem"
HEXMAP = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
KEYLENGTH = general_config["keylength"]

logger = logging.getLogger(__name__)
_storage = Storage("security", "private")


def get_uuid():
    pubder = get_private_key().export_pubkey_der()
    dig = sha1(pubder).digest()[:16]
    return binascii.b2a_hex(dig)


def get_serial():
    return uuid_to_short(get_uuid())


def get_private_key():
    if _storage.exists(KEYNAME):
        try:
            with _storage.open(KEYNAME, "r") as f:
                return RSAObject(pem=f.read())
        except Exception:
            logger.exception("Error while get private key")

    rsaobj = RSAObject(keylength=KEYLENGTH)
    pem = rsaobj.export_pem()
    with _storage.open(KEYNAME, "w") as f:
        f.write(pem)
    logger.info("Private key created at: %s" % _storage.get_path(KEYNAME))
    return rsaobj


def uuid_to_short(uuid_hex, mapping=HEXMAP):
    u = UUID(uuid_hex)
    l = len(mapping)
    n = u.int
    a_short = []
    while n > 0:
        c = mapping[n % l]
        n = n // l
        a_short.append(c)

    while len(a_short) < 25:
        a_short.append(mapping[0])

    return "".join(a_short)
