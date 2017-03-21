
from select import select
import msgpack
import socket

from fluxmonitor.config import HALCONTROL_ENDPOINT
from fluxmonitor.err_codes import SUBSYSTEM_ERROR


def toolhead_on():
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(HALCONTROL_ENDPOINT)
        s.send(b'\x92\xa5th_on\xc3\x92\xa3bye\xc2')
        rl = select((s, ), (), (), 0.1)[0]
        if rl:
            try:
                payload = msgpack.unpackb(s.recv(4096))
                if payload[1] != "ok":
                    raise SystemError(SUBSYSTEM_ERROR, "HAL", *payload[2:])
            except Exception:
                raise SystemError(SUBSYSTEM_ERROR, "HAL_PROTOCOL_ERROR")
    finally:
        s.close()


def toolhead_standby():
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(HALCONTROL_ENDPOINT)
        s.send(b'\x92\xaath_standby\xc2')
    finally:
        s.close()


def toolhead_power_on():
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(HALCONTROL_ENDPOINT)
        s.send(b'\x92\xa9th_pow_on\xc3\x92\xa3bye\xc2')
        rl = select((s, ), (), (), 0.1)[0]
        if rl:
            try:
                payload = msgpack.unpackb(s.recv(4096))
                if payload[1] != "ok":
                    raise SystemError(SUBSYSTEM_ERROR, "HAL", *payload[2:])
            except Exception:
                raise SystemError(SUBSYSTEM_ERROR, "HAL_PROTOCOL_ERROR")
    finally:
        s.close()


def toolhead_power_off():
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(HALCONTROL_ENDPOINT)
        s.send(b'\x92\xaath_pow_off\xc2')
    finally:
        s.close()


def delay_toolhead_poweroff():
    from fluxmonitor.storage import Metadata
    Metadata.instance().delay_toolhead_poweroff = b"\x01"


def reset_mb():
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(HALCONTROL_ENDPOINT)
        s.send(b'\x92\xa8reset_mb\xc2')
    finally:
        s.close()


def begin_hal_diagnosis():
    s = socket.socket(socket.AF_UNIX)
    s.setblocking(False)
    s.connect(HALCONTROL_ENDPOINT)
    s.send(b'\x92\xaediagnosis_mode\xc2')
    return s


def hal_diagnosis_result(sock):
    try:
        payload = msgpack.unpackb(sock.recv(4096))
        return payload[1]
    except Exception:
        return "SUBSYSTEM_ERROR HAL_PROTOCOL_ERROR"
