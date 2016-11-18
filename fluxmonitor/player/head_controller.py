
from ._head_controller import (
    HeadController, ExtruderExt, HeadError, HeadOfflineError, HeadResetError,
    HeadTypeError,
)

from fluxmonitor.err_codes import (
    EXEC_HEAD_ERROR, HARDWARE_FAILURE, EXEC_HEAD_CALIBRATING,
    EXEC_HEAD_INTERLOCK_TRIGGERED, EXEC_HEAD_FAN_FAILURE, EXEC_HEAD_TILT,
    EXEC_HEAD_SHAKE, EXEC_BAD_COMMAND)


__all__ = ["exec_command", "check_toolhead_errno",
           "HeadController", "HeadError", "HeadOfflineError", "HeadResetError",
           "HeadTypeError"]


def exec_command(toolhead, cmd):
    action = cmd[0]
    if action == "H" and isinstance(toolhead.ext, ExtruderExt):
        idx = int(cmd[1])
        val = float(cmd[2:])
        toolhead.ext.set_heater(idx, val)
    elif action == "F" and isinstance(toolhead.ext, ExtruderExt):
        idx = int(cmd[1])
        val = float(cmd[2:])
        toolhead.ext.set_fanspeed(idx, val)
    else:
        raise SystemError(EXEC_HEAD_ERROR, EXEC_BAD_COMMAND)


def check_toolhead_errno(toolhead, mask):
    errno = toolhead.error_code & mask
    if errno:
        str_errno = str(errno)
        if errno & 8:
            raise HeadCalibratingError(str_errno)
        if errno & 16:
            raise HeadShakeError(str_errno)
        if errno & 32:
            raise HeadShakeError(str_errno)
        if errno & 576:
            raise HeadHardwareError(str_errno, toolhead.status.get("HE"))
        if errno & 128:
            raise HeadFanError(str_errno)
        if errno & 256:
            raise HeadInterlockTriggered(str_errno)
        raise HeadError(EXEC_HEAD_ERROR, "?", str_errno)


class HeadCalibratingError(HeadError):
    def __init__(self, errno):
        HeadError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_CALIBRATING, errno)


class HeadShakeError(HeadError):
    hw_error_code = 50

    def __init__(self, errno):
        HeadError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_SHAKE, errno)


class HeadTiltError(HeadError):
    hw_error_code = 50

    def __init__(self, errno):
        HeadError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_TILT, errno)


class HeadHardwareError(HeadError):
    def __init__(self, errno, he=None):
        if he:
            HeadError.__init__(self, EXEC_HEAD_ERROR, HARDWARE_FAILURE,
                               errno, he)
        else:
            HeadError.__init__(self, EXEC_HEAD_ERROR, HARDWARE_FAILURE, errno)


class HeadFanError(HeadError):
    hw_error_code = 52

    def __init__(self, errno):
        HeadError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_FAN_FAILURE, errno)


class HeadInterlockTriggered(HeadError):
    hw_error_code = 49

    def __init__(self, errno):
        HeadError.__init__(self, EXEC_HEAD_ERROR,
                           EXEC_HEAD_INTERLOCK_TRIGGERED, errno)
