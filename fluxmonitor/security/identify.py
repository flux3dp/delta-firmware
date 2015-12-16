
from uuid import UUID
import binascii
import logging

from fluxmonitor.security._security import get_rsakey as _get_rsakey, \
    get_uuid as _get_uuid, get_identify as _get_identify, \
    get_serial_number as _get_serial_number

HEXMAP = "123456789ABCDEFGHJKLMNOPQRSTUVWXYZ"

logger = logging.getLogger(__name__)

_keycache = None
_uuidcache = None
_serialcache = None
_identifycache = None
_rescue = None


def __checkenv__():
    global _keycache, _uuidcache, _rescue, _identifycache, _serialcache
    if not _keycache:
        try:
            _keycache = _get_rsakey()
            _uuidcache = _get_uuid()
            _serialcache = _get_serial_number()
            _identifycache = _get_identify()
            _rescue = False
        except Exception:
            logger.exception("#### Fetch device key failed!! ####")
            _keycache = _get_rsakey(rescue=True)
            _uuidcache = _get_uuid(rescue=True)
            _serialcache = "XXXXXXXXXX"
            _identifycache = "WASUREMONO"
            _rescue = True


def get_uuid():
    __checkenv__()
    return binascii.b2a_hex(_uuidcache)


def get_serial():
    __checkenv__()
    return _serialcache


def rescue_mode():
    __checkenv__()
    return _rescue


def get_private_key():
    __checkenv__()
    return _keycache


def get_identify():
    __checkenv__()
    return _identifycache


def _uuid_to_short(uuid_hex, mapping=HEXMAP):
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
