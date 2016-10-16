
from fluxmonitor.security import get_uuid, get_serial
from fluxmonitor import halprofile, __version__ as version

if halprofile.CURRENT_MODEL == halprofile.MODEL_D1:
    from .raspberry_1 import _get_deviceinfo
else:
    from .dev import _get_deviceinfo

__all__ = ["get_deviceinfo"]
UUID_HEX = get_uuid()
SERIAL = get_serial()


def get_deviceinfo(metadata=None):
    if metadata:
        info = {
            "version": version, "model": halprofile.get_model_id(),
            "uuid": UUID_HEX, "serial": SERIAL, "nickname": metadata.nickname,
            "cloud": metadata.cloud_status
        }
    else:
        info = {
            "version": version, "model": halprofile.get_model_id(),
            "uuid": UUID_HEX, "serial": SERIAL
        }
    info.update(_get_deviceinfo())
    return info
