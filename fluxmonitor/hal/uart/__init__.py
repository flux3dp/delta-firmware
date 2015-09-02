
from fluxmonitor import halprofile



def get_uart_hal(require_model=None):
    if not require_model:
        require_model = halprofile.CURRENT_MODEL

    if require_model == halprofile.MODEL_DARWIN_DEV:
        from .dev import UartHal
        return UartHal
    elif require_model == halprofile.MODEL_LINUX_DEV:
        from .dev import UartHal
        return UartHal
    elif require_model == "smoothie":
        from .smoothie import UartHal
        return UartHal
    elif require_model == halprofile.MODEL_G1:
        from .raspberry_1 import UartHal
        return UartHal

    raise RuntimeError("NOT IMPLEMENT")
