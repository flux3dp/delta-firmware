
from fluxmonitor.config import network_config
from fluxmonitor.misc import Process

DEBUG = network_config.get("debug", False)

# hack it >>>>>>>>>>>>>>>>>>>>>>>>
# We modify nl80211 for linux and it will print what it do.
# It is useful to debug when running under mac os, because
# it is meaningless to implement thease function under mac os.

from . import _config_linux


def __new_caller__(args):
    if DEBUG:
        print("# %s" % " ".join(args))
    return "", ""


def __process_middle__(manager, args):
    if DEBUG:
        print("# %s" % " ".join(args))
    return Process(manager, ["sleep", "60"])


def __config_nameserver(nameservers):
    if DEBUG:
        print("# config_nameserver: %s" % nameservers)


class FakeIPR(object):
    def link_up(self, index):
        if DEBUG:
            print("# ifup %s" % index)

    def link_down(self, index):
        if DEBUG:
            print("# ifdown %s" % index)

    def addr(self, *args, **kw):
        if DEBUG:
            print("ip", args, kw)

    def route(self, *args, **kw):
        if DEBUG:
            print("route", args, kw)


_config_linux.IPRoute = FakeIPR
_config_linux.Process = __process_middle__
_config_linux.config_nameserver = __config_nameserver

_config_linux.find_device_index = lambda ifname: 2
_config_linux.get_ipaddresses = lambda index: [("192.168.123.123", 24),
                                               ("192.168.123.124", 24)]
_config_linux.get_gateways = lambda: ["192.168.123.1"]
# <<<<<<<<<<<<<<<<<<<<<<<< end of hack

__all__ = ["ifup", "ifdown", "wlan_managed_daemon", "wlan_ap_daemon",
           "dhcp_client_daemon", "config_ipaddr", "config_nameserver",
           "dhcp_server_daemon"]


def ifup(ifname):
    return _config_linux.ifup(ifname)


def ifdown(ifname):
    return _config_linux.ifdown(ifname)


def wlan_managed_daemon(manager, ifname, wlan_config):
    return _config_linux.wlan_managed_daemon(manager, ifname, wlan_config)


def wlan_ap_daemon(manager, ifname):
    return _config_linux.wlan_ap_daemon(manager, ifname)


def dhcp_client_daemon(manager, ifname):
    return _config_linux.dhcp_client_daemon(manager, ifname)


def dhcp_server_daemon(manager, ifname):
    return _config_linux.dhcp_server_daemon(manager, ifname)


def config_ipaddr(ifname, config):
    return _config_linux.config_ipaddr(ifname, config)

config_nameserver = __config_nameserver
