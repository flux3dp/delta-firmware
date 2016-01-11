
import socket
import os


def create_unix_socket(path):
    if os.path.exists(path):
        os.unlink(path)
    us = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    us.bind(path)
    us.setblocking(False)

    return us
