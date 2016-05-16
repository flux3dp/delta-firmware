
import logging

from fluxmonitor.misc import Process

logger = logging.getLogger(__name__)

__all__ = ["wlan_managed_daemon", "wlan_ap_daemon", "get_wlan_ssid",
           "check_associate"]


def wlan_managed_daemon(manager, ifname, wlan_config):
    logger.info("wpa %s: %s" % (ifname, wlan_config))
    return Process(manager, ["sleep", "60"])


def wlan_ap_daemon(manager, ifname):
    logger.info("hostapd %s: %s" % ifname)
    return Process(manager, ["sleep", "60"])


def get_wlan_ssid(ifname):
    return "FLUX AP"


def check_associate(ifname="wlan0"):
    return True
