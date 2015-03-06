
from subprocess import Popen, PIPE, call
import platform
import logging
import re

logger = logging.getLogger(__name__)

from fluxmonitor.misc import call_and_return_0_or_die
from fluxmonitor.config import network_config

__all__ = ["ifup", "ifdown", "wlan_config", "wlan_config_retry", "wlan_adhoc", "ping_wpa_supplicant"]

ADHOC_SSID = network_config['adhoc-ssid']
IFUP = network_config['ifup']
IFDOWN = network_config['ifdown']
WPA_CLI = network_config['wpa_cli']

def ifup(ifname):
    logger.info("%s up" % ifname)
    try:
        call_and_return_0_or_die(["sudo", "-n", IFUP, ifname])
        return True
    except RuntimeError as error:
        logger.error("ifup fail: %s" % error)
        return False

def ifdown(ifname):
    logger.info("%s down" % ifname)
    try:
        call_and_return_0_or_die(["sudo", "-n", IFDOWN, ifname])
        return True
    except RuntimeError as error:
        logger.error("ifdown fail: %s" % error)
        return False

def wlan_config(ifname, network_type, ssid, psk=None, wep_key=None):
    """Set wireless associate with an access point

    fluxmonitor always place network config at network id 0, so it will drop
    all network and recreate one."""

    # network_type should be: "", "WEP", "WPA-PSK", "WPA2-PSK"
    if network_type == "": pass
    elif network_type == "WEP":
        if not wep_key:
            raise RuntimeError("wep_key param required for WEP network type")
    elif network_type in ("WPA-PSK", "WPA2-PSK"):
        if not psk:
            raise RuntimeError("psk param required for WPA-PSK or WPA2-PSK network type")
    else:
        raise RuntimeError("Can not handle network type: %s" % network_type)

    # Delete all settings...
    drop_all_wpa_network_config(ifname)

    # Then create a new one
    stdout, _ = call_and_return_0_or_die([WPA_CLI, "-i", ifname, "add_network"])
    network_id = stdout.strip().split("\n")[-1]
    if not (network_id.isdigit() and int(network_id) == 0):
        raise RuntimeError("wpa_cli return network id should be 0 but get %s" %
            network_id)

    wpa_cli_cmd(ifname, ["set_network", "0", "ssid", "\"%s\"" % ssid])
    wpa_cli_cmd(ifname, ["set_network", "0", "mode", "0"])

    if network_type == "":
        wpa_cli_cmd(ifname, ["set_network", "0", "key_mgmt", "NONE"])
    elif network_type == "WEP":
        wpa_cli_cmd(ifname, ["set_network", "0", "wep_key0", "\"%s\"" % wep_key])
        wpa_cli_cmd(ifname, ["set_network", "0", "key_mgmt", "NONE"])
    elif network_type in ["WPA-PSK", "WPA2-PSK"]:
        wpa_cli_cmd(ifname, ["set_network", "0", "key_mgmt", "WPA-PSK"])
        wpa_cli_cmd(ifname, ["set_network", "0", "psk", "%s" % psk])
        wpa_cli_cmd(ifname, ["set_network", "0", "proto", "RSN"])

    wpa_cli_cmd(ifname, ["select_network", "0"])
    wpa_cli_cmd(ifname, ["enable_network", "0"])
    wpa_cli_cmd(ifname, ["reassociate"])

def wlan_config_retry(ifname):
    if 0 in list_wpa_network_ids(ifname):
        o, _ = call_and_return_0_or_die([WPA_CLI, "-i", ifname, "get_network", "0", "mode"])
        if o.strip() != "0": raise RuntimeError("Network config not exist (wrong mode)")

        wpa_cli_cmd(ifname, ["select_network", "0"])
        wpa_cli_cmd(ifname, ["enable_network", "0"])
        wpa_cli_cmd(ifname, ["reassociate"])
    else:
        raise RuntimeError("Network config not exist (network id not found)")

def wlan_adhoc(ifname):
    """Set wireless to ad-hoc mode

    Ad-hoc will use network id:
        0: if no network config exist
        1: has network config but can not access
    
    All network settings with network id > 1 will be droped."""

    network_ids = list_wpa_network_ids(ifname)
    for id in network_ids:
        if id >= 1: drop_wpa_network_config(id)

    stdout, _ = call_and_return_0_or_die([WPA_CLI, "add_network"])
    network_id = stdout.strip().split("\n")[-1]

    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "ssid", "\"%s\"" % ADHOC_SSID])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "mode", "1"])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "pairwise", "NONE"])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "group", "TKIP"])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "frequency", "2432"])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "key_mgmt", "WPA-NONE"])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "proto", "WPA"])
    wpa_cli_cmd(ifname, ["-i", ifname, "set_network", network_id, "psk", "\"%s\"" % "1234567890123"])

    wpa_cli_cmd(ifname, ["-i", ifname, "select_network", network_id])
    wpa_cli_cmd(ifname, ["-i", ifname, "enable_network", network_id])
    wpa_cli_cmd(ifname, ["-i", ifname, "reassociate"])

def ping_wpa_supplicant(ifname):
    try:
        o, _ = call_and_return_0_or_die([WPA_CLI, "-i", ifname, "ping"])
        return o.strip().split("\n")[1] == "PONG"
    except Exception:
        return False

# Private methods
def list_wpa_network_ids(ifname):
    stdout, _ = call_and_return_0_or_die(
        [WPA_CLI, "-i", ifname, "list_network"])

    ids = []
    for row in stdout.split("\n"):
        network_id = re.split(r'\s+', row, 1)[0]
        if network_id.isdigit(): ids.append(int(network_id))

    return ids

def drop_all_wpa_network_config(ifname):
    for id in list_wpa_network_ids(ifname):
        drop_wpa_network_config(ifname, id)

def drop_wpa_network_config(ifname, network_id):
    call_and_return_0_or_die([WPA_CLI, "-i", ifname, "remove_network", str(network_id)])

def wpa_cli_cmd(ifname, args):
    o, _ = call_and_return_0_or_die([WPA_CLI, "-i", ifname] + args)
    msg = o.strip().split("\n")[-1]
    if msg != "OK":
        raise RuntimeError("Command `%s` return %s" % (" ".join([WPA_CLI] + args), msg))

