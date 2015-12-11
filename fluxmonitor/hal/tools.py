
import socket

from fluxmonitor.config import uart_config


def reset_mb():
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(uart_config["control"])
        s.send(b"reset mb")
    except Exception:
        L.exception("Error while send resset mb signal")
