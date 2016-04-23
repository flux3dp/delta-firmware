
import socket

from fluxmonitor.config import uart_config


def reset_mb():
    s = socket.socket(socket.AF_UNIX)
    s.connect(uart_config["control"])
    s.send(b"reset_mb")


def reset_hb():
    s = socket.socket(socket.AF_UNIX)
    s.connect(uart_config["control"])
    s.send(b"reset_hb")
