
from errno import EAGAIN
import socket
import sys

class IPRoute(object):
    def __init__(self):
        self.__pipe = socket.socketpair()
        self.__pipe[0].setblocking(False)

    def bind(self): pass

    def fileno(self): return self.__pipe[0].fileno()

    def get(self):
        try: self.__pipe[0].recv(4096)
        except socket.error as e:
            if not hasattr("errno", e) or e.errno != EAGAIN:
                raise
        return []

    def get_links(self):
        return [
            {"attrs": {"IFLA_IFNAME": "lo"}},
            {"attrs": {"IFLA_IFNAME": "wlan0", "IFLA_ADDRESS": "ff:ff:ff:ff:ff:ff", "IFLA_OPERSTATE": "UP"}, "index": 1}
        ]

    def get_addr(self):
        return [
            {"attrs": {"IFA_LABEL": "lo"}},
            {"attrs": {"IFA_LABEL": "wlan0", "IFA_ADDRESS": "99.99.99.99"}}
        ]

