
from subprocess import Popen, PIPE, call
import platform
import re

from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.misc import Process

# hack it >>>>>>>>>>>>>>>>>>>>>>>>
# We modify nl80211 for linux and it will print what it do.
# It is useful to debug when running under mac os, because
# it is meaningless to implement this function under mac os.

from . import _config_linux

def __new_caller__(args):
    print("# %s" % " ".join(args))
    return "", ""

def __process_middle__(manager, args):
    print("# %s" % " ".join(args))
    return Process(manager, ["sleep", "5"])

_config_linux.Process = __process_middle__
_config_linux.call_and_return_0_or_die = __new_caller__
# <<<<<<<<<<<<<<<<<<<<<<<< end of hack

__all__ = ["ifup", "ifdown", "wlan_managed_daemon", "wlan_ap_daemon", "dhcp_client_daemon"]

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

def config_ipaddr(manager, ifname, config):
    return _config_linux.config_ipaddr(manager, ifname, config)
