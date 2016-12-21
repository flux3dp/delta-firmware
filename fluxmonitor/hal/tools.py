
import socket

from fluxmonitor.config import HALCONTROL_ENDPOINT


def reset_mb():
    s = socket.socket(socket.AF_UNIX)
    s.connect(HALCONTROL_ENDPOINT)
    s.send(b'\x92\xa8reset_mb\xc2')
    s.close()


def reset_hb():
    s = socket.socket(socket.AF_UNIX)
    s.connect(HALCONTROL_ENDPOINT)
    s.send(b'\x92\xa8reset_hb\xc2')
    s.close()
