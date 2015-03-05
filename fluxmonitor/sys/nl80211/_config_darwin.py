
from subprocess import Popen, PIPE, call
import platform
import re

from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.misc import call_and_return_0_or_die

# hack it >>>>>>>>>>>>>>>>>>>>>>>>
# We modify nl80211 for linux and it will print what it do.
# It is useful to debug when running under mac os, because
# it is meaningless to implement this function under mac os.

from . import _config_linux

def __do_nothing__(*args, **kw): pass

def __wpa_cli__(args):
    print("# %s" % " ".join(args))

    # Return fake message
    if "add_network" in args: return "0", ""
    else: return "OK", ""

_config_linux.drop_config = __do_nothing__
_config_linux.call_and_return_0_or_die = __wpa_cli__
# <<<<<<<<<<<<<<<<<<<<<<<< end of hack

__all__ = ["ifup", "ifdown", "wlan_config", "ping_wpa_supplicant"]

def ifup(ifname):
    _config_linux.ifup(ifname)

def ifdown(ifname):
    _config_linux.ifdown(ifname)

def wlan_config(options):
    _config_linux.wlan_config(options)

def ping_wpa_supplicant(ifname):
    _config_linux.ping_wpa_supplicant(ifname)
    if ifname.startswith("wlan"):
        return Monitor().full_status().get(ifname, {}).get('ifstatus') == 'UP'
    else:
        return False
