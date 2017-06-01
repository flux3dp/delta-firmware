
import socket

from fluxmonitor.config import MAINBOARD_ENDPOINT, HEADBOARD_ENDPOINT


def create_mainboard_socket():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(MAINBOARD_ENDPOINT)
    except Exception:
        s.close()
        raise

    return s


def create_toolhead_socket():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(HEADBOARD_ENDPOINT)
    except Exception:
        s.close()
        raise

    return s
