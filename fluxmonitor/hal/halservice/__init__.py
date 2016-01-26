
from fluxmonitor import halprofile


def get_halservice(require_model=None):
    if not require_model:
        require_model = halprofile.CURRENT_MODEL

    if require_model == halprofile.MODEL_DARWIN_DEV:
        from .dev import UartHal
        return UartHal
    elif require_model == halprofile.MODEL_LINUX_DEV:
        from .dev import UartHal
        return UartHal
    elif require_model == "manually":
        from .smoothie import UartHal
        return UartHal
    elif require_model == halprofile.MODEL_D1:
        from .raspberry_1 import UartHal
        return UartHal

    raise RuntimeError("NOT IMPLEMENT")
