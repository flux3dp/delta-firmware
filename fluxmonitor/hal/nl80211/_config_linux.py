
import tempfile
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.misc import Process
from fluxmonitor.config import network_config

WPA_SUPPLICANT = network_config['wpa_supplicant']
HOSTAPD = network_config['hostapd']

__all__ = ["wlan_managed_daemon", "wlan_ap_daemon", "get_wlan_ssid"]


def wlan_managed_daemon(manager, ifname, wlan_config):
    logger.info("wpa %s: %s" % (ifname, wlan_config))

    conf_file = tempfile.mktemp() + ".wpa.conf"
    _write_wpa_config(conf_file, wlan_config)

    return Process(manager,
                   [WPA_SUPPLICANT, "-i", ifname, "-D", "nl80211,wext",
                    "-c", conf_file])


def wlan_ap_daemon(manager, ifname):
    logger.info("hostapd %s" % ifname)

    conf_file = tempfile.mktemp() + ".hostapd.conf"
    _write_hostapd_config(conf_file, ifname, {})

    return Process(manager, [HOSTAPD, conf_file])


def get_wlan_ssid(ifname="wlan0"):
    return Process.call_with_output("iwgetid", "-r", ifname).strip()


def _write_wpa_config(filepath, config):
    security = config.get("security")
    buf = None

    if security == "":
        buf = """network={
            ssid="%(ssid)s"
            mode=0
            key_mgmt=NONE
}""" % config

    elif security == "WEP":
        buf = """network={
            ssid="%(ssid)s"
            mode=0
            wep_key0="%(wepkey)s"
            key_mgmt=NONE
}""" % config

    elif security in ["WPA-PSK", "WPA2-PSK"]:
        # TODO: Need to rewrite
        if len(config["psk"]) != 64:
            # TODO: Remove unencrypted method
            buf = """network={
                ssid="%(ssid)s"
                mode=0
                psk="%(psk)s"
                proto=RSN
                key_mgmt=WPA-PSK
}""" % config
        else:
            buf = """network={
                ssid="%(ssid)s"
                mode=0
                psk=%(psk)s
                proto=RSN
                key_mgmt=WPA-PSK
}""" % config

    else:
        raise RuntimeError("Uknow wireless security: " + security)

    with open(filepath, "w") as f:
        f.write(buf)


def _write_hostapd_config(filepath, ifname, config):
    buf = """# Create by fluxmonitord
interface=%(ifname)s
ssid=%(name)s
hw_mode=g
channel=11
""" % {"ifname": ifname, "name": config.get("name", "FLUX-3D-Printer")}

    with open(filepath, "w") as f:
        f.write(buf)
