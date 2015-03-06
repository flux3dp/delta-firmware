
import platform
import logging
import tempfile
import re

logger = logging.getLogger(__name__)

from fluxmonitor.misc import call_and_return_0_or_die, Process
from fluxmonitor.misc import linux_configure
from fluxmonitor.config import network_config

__all__ = ["ifup", "ifdown", "wlan_managed_daemon", "wlan_ap_daemon", "dhcp_client_daemon"]

IFCONFIG = network_config['ifconfig']
WPA_SUPPLICANT = network_config['wpa_supplicant']
HOSTAPD = network_config['hostapd']
DHCLIENT = network_config['dhclient']


def ifup(ifname):
    logger.info("%s up" % ifname)
    try:
        call_and_return_0_or_die(["sudo", "-n", IFCONFIG, ifname, 'up'])
        return True
    except RuntimeError as error:
        logger.error("ifup fail: %s" % error)
        return False

def ifdown(ifname):
    logger.info("%s down" % ifname)
    try:
        call_and_return_0_or_die(["sudo", "-n", IFCONFIG, ifname, 'down'])
        return True
    except RuntimeError as error:
        logger.error("ifdown fail: %s" % error)
        return False

def wlan_managed_daemon(manager, ifname, wlan_config):
    wpa_conf = tempfile.mktemp() + ".conf"
    linux_configure.wpa_supplicant_config_to_file(wpa_conf, wlan_config)

    return Process(manager,
        ["sudo", "-n", WPA_SUPPLICANT, "-i", ifname, "-D", "nl80211,wext", "-c", wpa_conf])

def wlan_ap_daemon(manager, ifname):
    return Process(manager,
        ["sudo", "-n", HOSTAPD, "-i", ifname, "/etc/hostapd/hostapd.conf"])

def dhcp_client_daemon(manager, ifname):
    return Process(manager, ["sudo", "-n", DHCLIENT, "-d", ifname])

def config_ipaddr(manager, ifname, config):
    raise RuntimeError("Not implement")
