
import binascii
import logging

from fluxmonitor.security import _security

logger = logging.getLogger(__name__)

_keycache = None
_uuidcache = None
_serialcache = None
_model_id = None
_identifycache = None
_rescue = None


def __checkenv__():  # noqa
    global _keycache, _uuidcache, _rescue, _identifycache, _serialcache
    if not _keycache:
        try:
            _keycache = _security.get_rsakey()
            _uuidcache = _security.get_uuid()
            _serialcache = _security.get_serial_number()
            _identifycache = _security.get_identify()
            _rescue = False
        except Exception:
            logger.exception("#### Fetch device key failed!! ####")
            _keycache = _security.get_rsakey(rescue=True)
            _uuidcache = _security.get_uuid(rescue=True)
            _serialcache = "XXXXXXXXXX"
            _identifycache = "WASUREMONO"
            _rescue = True


def get_model_id():
    global _model_id
    if _model_id is None:
        _model_id = _security.get_model_id()
    return _model_id


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


get_platform = _security.get_platform
