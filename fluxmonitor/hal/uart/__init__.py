
from fluxmonitor import halprofile

def get_uart_hal():
    if halprofile.CURRENT_MODEL == halprofile.MODEL_DARWIN_DEV:
        from .dev import UartHal
        return UartHal
    elif halprofile.CURRENT_MODEL == halprofile.MODEL_LINUX_DEV:
        from .dev import UartHal
        return UartHal
    elif halprofile.CURRENT_MODEL == halprofile.MODEL_MODEL_G1:
        raise RuntimeError("NOT READY")

    raise RuntimeError("NOT IMPLEMENT")
