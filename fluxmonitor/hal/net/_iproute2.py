
__doc__ = """
This is a fake implement for iproute2 module to debug under macos.
Note: iproute2 is using netlink tech and it is available on linux only.
"""

from errno import EAGAIN
from time import sleep
import threading
import socket
import struct

import netifaces


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]
    return getinstance


def get_prefixlen(mask):
    n = struct.unpack(">I", socket.inet_aton(mask))[0]
    for i in range(32):
        if (n >> i) & 1:
            return 32 - i


def valid_device(ifname):
    return ifname.startswith("en") or ifname.startswith("eth") or \
        ifname.startswith("ppp") or ifname.startswith("lo")


def get_mac_addr(ifname):
    addr = netifaces.ifaddresses(ifname).get(netifaces.AF_LINK)
    if addr:
        return addr[0].get("addr", "ff:ff:ff:ff:ff:ff")
    else:
        return "ff:ff:ff:ff:ff:ff"


def get_ip_addr(ifname):
    addrs = netifaces.ifaddresses(ifname).get(netifaces.AF_INET, {})

    return [{
        "attrs": [
            ["IFA_LABEL", ifname],
            ["IFA_ADDRESS", addr["addr"]],
        ],
        "prefixlen": get_prefixlen(addr["netmask"]),
    } for addr in addrs]


@singleton
class IPRoute(object):
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
        """
        Return data should like this:
        [
            {"attrs": [["IFLA_IFNAME", "lo"]]},
            {"attrs": [["IFLA_IFNAME", "wlan0"],
                       ["IFLA_ADDRESS", "ff:ff:ff:ff:ff:ff"],
                       ["IFLA_OPERSTATE", "DOWN"]],
             "index": 1}
        ]
        """
        links = []
        for ifname in netifaces.interfaces():
            if valid_device(ifname):
                state = "UP" if get_ip_addr(ifname) else "DOWN"
                links.append({
                    "attrs": [
                        ["IFLA_IFNAME", ifname],
                        ["IFLA_ADDRESS", get_mac_addr(ifname)],
                        ["IFLA_OPERSTATE", state]],
                    "index": len(links) + 1
                })
        return links

    def get_addr(self):
        """
        Return data should like this
        [
            {"attrs": [["IFA_LABEL", "lo"]]},
            {"attrs": [["IFA_LABEL", "wlan0"],
                       ["IFA_ADDRESS", socket.gethostbyname(hn)]],
             "prefixlen": 24}
        ]
        """
        addrs = []
        for ifname in netifaces.interfaces():
            if valid_device(ifname):
                for addr in get_ip_addr(ifname):
                    addrs += get_ip_addr(ifname)
        return addrs

    def close(self):
        pass
