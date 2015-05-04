
__doc__ = """
This is a fake implement for iproute2 module to debug under macos.
Note: iproute2 is using netlink tech and it is available on linux only.
"""

from time import sleep
from errno import EAGAIN
import threading
import socket


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]
    return getinstance


@singleton
class IPRoute(object):
    # Simulate data source
    links = [
        {"attrs": [["IFLA_IFNAME", "lo"]]},
        {"attrs": [["IFLA_IFNAME", "wlan0"],
                   ["IFLA_ADDRESS", "ff:ff:ff:ff:ff:ff"],
                   ["IFLA_OPERSTATE", "DOWN"]],
         "index": 1}
    ]

    # Simulate data source
    addrs = [
        {"attrs": {"IFA_LABEL": "lo"}},
        # {"attrs": {"IFA_LABEL": "wlan0", "IFA_ADDRESS": "99.99.99.99"}}
    ]

    def __init__(self):
        self.__pipe = socket.socketpair()
        self.__pipe[0].setblocking(False)
        self.__poker = threading.Thread(target=self.__poke__)
        self.__poker.setDaemon(True)
        self.__poker.start()

    def __poke__(self):
        while True:
            sleep(60.)
            self.trigger_status_changed()

    def bind(self):
        pass

    def fileno(self):
        return self.__pipe[0].fileno()

    def get(self):
        try:
            self.__pipe[0].recv(4096)
        except socket.error as e:
            if not hasattr(e, "errno") or e.errno != EAGAIN:
                raise
        return [{}]

    # Simulate data source control
    def trigger_status_changed(self, ifname=None, addip=None, removeip=None,
                               ifstate=None):
        if ifname:
            if addip:
                self.addrs.append({"attrs": {"IFA_LABEL": ifname,
                                             "IFA_ADDRESS": addip}})
            if removeip:
                self.addrs.remove({"attrs": {"IFA_LABEL": ifname,
                                             "IFA_ADDRESS": removeip}})
            if ifstate:
                for row in self.links:
                    if row["attrs"].get("IFLA_IFNAME") == ifname:
                        row["attrs"]["IFLA_OPERSTATE"] = ifstate

        self.__pipe[1].send(b"0")

    def get_links(self):
        return self.links

    def get_addr(self):
        hn = socket.gethostname()
        try:
            return [
                {"attrs": [["IFA_LABEL", "lo"]]},
                {"attrs": [["IFA_LABEL", "wlan0"],
                           ["IFA_ADDRESS", socket.gethostbyname(hn)]],
                 "prefixlen": 24}
            ]
        except socket.gaierror:
            return [{"attrs": [["IFA_LABEL", "lo"]]}]
