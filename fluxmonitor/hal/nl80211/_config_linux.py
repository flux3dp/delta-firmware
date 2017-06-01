
import tempfile
import logging

from fluxmonitor.misc import Process
from fluxmonitor.config import network_services

logger = logging.getLogger(__name__)
WPA_SUPPLICANT = network_services['wpa_supplicant']
HOSTAPD = network_services['hostapd']

__all__ = ["wlan_managed_daemon", "wlan_ap_daemon", "get_wlan_ssid",
           "check_associate"]


def wlan_managed_daemon(manager, ifname, wlan_config):
    logger.info("[%s] wpa: %s (%s)", ifname, wlan_config.get("ssid"),
                wlan_config.get("security"))

    conf_file = tempfile.mktemp() + ".wpa.conf"
    _write_wpa_config(conf_file, wlan_config)

    return Process(manager,
                   [WPA_SUPPLICANT, "-i", ifname, "-D", "nl80211,wext",
                    "-c", conf_file])


def wlan_ap_daemon(manager, ifname, config):
    logger.info("[%s] hostapd: %s", ifname, config.get("ssid"))

    conf_file = tempfile.mktemp() + ".hostapd.conf"
    _write_hostapd_config(conf_file, ifname, config)

    return Process(manager, [HOSTAPD, conf_file])


def get_wlan_ssid(ifname="wlan0"):
    return Process.call_with_output("iwgetid", "-r", ifname).strip()


def check_associate(ifname="wlan0"):
    return Process.fast_exec(("iwgetid", "-r", ifname))[0] == 0
    # ret = Process.call_with_output("iwgetid", "-a", ifname).strip()
    # if ret and ret[-17:] != '00:00:00:00:00:00':
    #     ret = Process.call_with_output("iwgetid", "-r", ifname).strip()

    # else:
    #     return False

    # return True if ret and ret[-17:] != '00:00:00:00:00:00' else False


def _write_wpa_config(filepath, config):
    security = config.get("security")
    if "scan_ssid" not in config:
        config["scan_ssid"] = "0"
    buf = None

    if security == "":
        buf = """network={
            ssid="%(ssid)s"
            mode=0
            scan_ssid=%(scan_ssid)s
            key_mgmt=NONE
}""" % config

    elif security == "WEP":
        buf = """network={
            ssid="%(ssid)s"
            key_mgmt=NONE
            wep_key0=%(wepkey)s
            scan_ssid=%(scan_ssid)s
            wep_tx_keyidx=0
            mode=0
}""" % config

    elif security in ["WPA-PSK", "WPA2-PSK"]:
        # TODO: Need to rewrite
        if len(config["psk"]) != 64:
            # TODO: Remove unencrypted method
            buf = """network={
                ssid="%(ssid)s"
                mode=0
                scan_ssid=%(scan_ssid)s
                psk="%(psk)s"
                proto=WPA RSN
                key_mgmt=WPA-PSK
}""" % config
        else:
            buf = """network={
                ssid="%(ssid)s"
                scan_ssid=%(scan_ssid)s
                mode=0
                psk=%(psk)s
                proto=WPA RSN
                key_mgmt=WPA-PSK
}""" % config

    else:
        raise RuntimeError("Uknow wireless security: " + security)

    with open(filepath, "w") as f:
        f.write(buf)


def _write_hostapd_config(filepath, ifname, config):
    security = config.get("security")
    if not security:
        buf = """# Create by fluxmonitord
interface=%(ifname)s
ssid=%(ssid)s
hw_mode=g
channel=11""" % {"ifname": ifname,
                 "ssid": config.get("ssid", "FLUX-3D-Printer")}

    elif security == "WPA2-PSK":
        buf = """# Create by fluxmonitord
interface=%(ifname)s
ssid=%(ssid)s
hw_mode=g
channel=11
country_code=FX
ieee80211n=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=%(psk)s""" % {"ifname": ifname,
                             "ssid": config.get("ssid", "FLUX-3D-Printer"),
                             "psk": config["psk"]}

    else:
        raise RuntimeError("Uknow wireless security: " + security)

    with open(filepath, "w") as f:
        f.write(buf)
