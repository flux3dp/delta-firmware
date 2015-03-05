
from subprocess import Popen, PIPE, call
import platform
import logging
import re

logger = logging.getLogger(__name__)

from fluxmonitor.misc import call_and_return_0_or_die

__all__ = ["ifup", "ifdown", "wlan_config", "ping_wpa_supplicant"]

def ifup(ifname):
    logger.info("%s up" % ifname)
    try:
        call_and_return_0_or_die(["sudo", "-n", "ifup", ifname])
        return True
    except RuntimeError as error:
        logger.error("ifup fail: %s" % error)
        return False

def ifdown(ifname):
    logger.info("%s down" % ifname)
    try:
        call_and_return_0_or_die(["sudo", "-n", "ifdown", ifname])
        return True
    except RuntimeError as error:
        logger.error("ifdown fail: %s" % error)
        return False

def wlan_config(options):
    # network_type should be: "", "WEP", "WPA-PSK", "WPA2-PSK"
    network_type = options['type']

    if network_type not in ("", "WEP", "WPA-PSK", "WPA2-PSK"):
        raise RuntimeError("Can not handle network type: %s" % network_type)

    ssid = options['ssid']
    wep_key0 = options.get('wepkey', '')
    psk = options.get('psk', '')

    # Delete all settings...
    drop_config()

    # Then create a new one
    stdout, _ = call_and_return_0_or_die(["wpa_cli", "add_network"])
    network_id = stdout.strip().split("\n")[-1]
    if not (network_id.isdigit() and int(network_id) == 0):
        raise RuntimeError("wpa_cli return network id should be 0 but get %s" %
            network_id)

    wpa_cli_cmd(["set_network", "0", "ssid", "\"%s\"" % ssid])
    wpa_cli_cmd(["set_network", "0", "mode", "0"])

    if network_type == "":
        wpa_cli_cmd(["set_network", "0", "key_mgmt", "NONE"])
    elif network_type == "WEP":
        wpa_cli_cmd(["set_network", "0", "wep_key0", "\"%s\"" % wep_key0])
        wpa_cli_cmd(["set_network", "0", "key_mgmt", "NONE"])
    elif network_type in ["WPA-PSK", "WPA2-PSK"]:
        wpa_cli_cmd(["set_network", "0", "key_mgmt", "WPA-PSK"])
        wpa_cli_cmd(["set_network", "0", "psk", "%s" % psk])
        wpa_cli_cmd(["set_network", "0", "proto", "RSN"])

    wpa_cli_cmd(["select_network", "0"])
    wpa_cli_cmd(["enable_network", "0"])
    wpa_cli_cmd(["reassociate"])
    wpa_cli_cmd(["save_config"])

def ping_wpa_supplicant(ifname):
    try:
        call_and_return_0_or_die(["wpa_cli", "-i", ifname])
        return True
    except Exception:
        return False

# Private methods
def drop_config():
    stdout, _ = call_and_return_0_or_die(
        ["sudo", "-n", "wpa_cli", "list_network"])

    for row in stdout.split("\n"):
        network_id = re.split(r'\s+', row, 1)[0]

        if network_id.isdigit():
            call_and_return_0_or_die(["wpa_cli", "remove_network", network_id])

def wpa_cli_cmd(args):
    o, _ = call_and_return_0_or_die(["wpa_cli"] + args)
    msg = o.strip().split("\n")[-1]
    if msg != "OK":
        raise RuntimeError("Command `%s` return %s" % (" ".join(["wpa_cli"] + args), msg))

