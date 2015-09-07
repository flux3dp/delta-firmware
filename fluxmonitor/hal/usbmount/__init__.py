
from fluxmonitor import halprofile


def get_usbmount_hal():
    m = halprofile.CURRENT_MODEL

    if m == halprofile.MODEL_DARWIN_DEV:
        from . import dev
        return dev
    elif m == halprofile.MODEL_LINUX_DEV:
        from . import dev
        return dev
    elif require_model == halprofile.MODEL_G1:
        from . import common_linux
        return common_linux

    raise RuntimeError("NOT IMPLEMENT")
