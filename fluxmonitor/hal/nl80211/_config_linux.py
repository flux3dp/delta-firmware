
import tempfile
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.misc import Process
from fluxmonitor.misc import linux_configure
from fluxmonitor.config import network_config

WPA_SUPPLICANT = network_config['wpa_supplicant']
HOSTAPD = network_config['hostapd']

__all__ = ["wlan_managed_daemon", "wlan_ap_daemon"]


def wlan_managed_daemon(manager, ifname, wlan_config):
    logger.info("wpa %s: %s" % (ifname, wlan_config))

    wpa_conf = tempfile.mktemp() + ".wpa.conf"
    linux_configure.wpa_supplicant_config_to_file(wpa_conf, wlan_config)

    return Process(manager,
                   [WPA_SUPPLICANT, "-i", ifname, "-D", "nl80211,wext",
                    "-c", wpa_conf])


def wlan_ap_daemon(manager, ifname):
    logger.info("hostapd %s: %s" % ifname)

    hostapd_conf = tempfile.mktemp() + ".hostapd.conf"
    linux_configure.hostapd_config_to_file(hostapd_conf, ifname)

    return Process(manager, [HOSTAPD, hostapd_conf])
