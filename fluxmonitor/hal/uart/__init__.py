
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
    elif require_model == halprofile.MODEL_MODEL_G1:
        raise RuntimeError("NOT READY")

    raise RuntimeError("NOT IMPLEMENT")
