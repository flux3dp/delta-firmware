
import tempfile
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.misc import Process
from fluxmonitor.misc import linux_configure
from fluxmonitor.config import network_config, platform

if platform == "linux":
    from pyroute2 import IPRoute


__all__ = ["ifup", "ifdown", "wlan_managed_daemon", "wlan_ap_daemon",
           "dhcp_client_daemon", "config_ipaddr", "config_nameserver",
           "dhcp_server_daemon"]

WPA_SUPPLICANT = network_config['wpa_supplicant']
HOSTAPD = network_config['hostapd']
DHCLIENT = network_config['dhclient']
DHCPD = network_config['dhcpd']


def ifup(ifname):
    index = find_device_index(ifname)
    logger.info("%s up" % ifname)
    ipr = IPRoute()
    ipr.link_up(index=index)


def ifdown(ifname):
    index = find_device_index(ifname)
    ipr = IPRoute()

    # Get all ip address and delete it
    for address, mask in get_ipaddresses(index):
        logger.info("Del ip %s/%s for %s" % (address, mask, ifname))
        ipr.addr('del', index=index, address=address, mask=mask)

    logger.info("%s down" % ifname)
    ipr.link_down(index=index)


def wlan_managed_daemon(manager, ifname, wlan_config):
    wpa_conf = tempfile.mktemp() + ".wpa.conf"
    linux_configure.wpa_supplicant_config_to_file(wpa_conf, wlan_config)

    return Process(manager,
                   [WPA_SUPPLICANT, "-i", ifname, "-D", "nl80211,wext",
                    "-c", wpa_conf])


def wlan_ap_daemon(manager, ifname):
    hostapd_conf = tempfile.mktemp() + ".hostapd.conf"
    linux_configure.hostapd_config_to_file(hostapd_conf, ifname)

    return Process(manager, [HOSTAPD, hostapd_conf])


def dhcp_client_daemon(manager, ifname):
    return Process(manager, [DHCLIENT, "-d", ifname])


def dhcp_server_daemon(manager, ifname):
    dhcpd_conf = tempfile.mktemp() + ".dhcpd.conf"
    dhcpd_leases = tempfile.mktemp() + ".leases"

    linux_configure.dhcpd_config_to_file(dhcpd_conf)
    with open(dhcpd_leases, "w"):
        pass

    return Process(manager, [DHCPD, "-f", "-cf", dhcpd_conf, "-lf",
                             dhcpd_leases])


def config_ipaddr(ifname, config):
    index = find_device_index(ifname)

    ipaddr = config["ipaddr"]
    mask = config["mask"]
    route = config.get("route")
    ns = config.get("ns")

    logger.info("Add ip %s/%s for %s" % (ipaddr, mask, ifname))
    ipr = IPRoute()
    ipr.addr('add', index=index, address=ipaddr, mask=mask)

    clean_route()

    if route:
        logger.info("Add gateway %s" % (route))
        ipr.route('add', gateway=route)

    if ns:
        config_nameserver(ns)


def config_nameserver(nameservers):
    """Config nameserver setting, the params is a list contains multi
    nameserviers"""

    with open("/etc/resolv.conf", "w") as f:
        f.write("# This file is overwrite by fluxmonitord\n\n")
        for row in nameservers:
            f.write("nameserver %s\n" % row)
        f.close()


# Private Methods
def find_device_index(ifname):
    ipr = IPRoute()
    devices = ipr.link_lookup(ifname=ifname)
    if len(devices) == 0:
        raise RuntimeError("Bad ifname %s" % ifname)
    return devices[0]


def clean_route():
    ipr = IPRoute()
    for g in get_gateways():
        try:
            ipr.route("delete", gateway=g)
        except Exception:
            logger.exception("Remove route error")


def get_ipaddresses(index):
    ipr = IPRoute()
    return [(i['attrs'][0][1], i['prefixlen'])
            for i in ipr.get_addr()
            if i['index'] == index]


def get_gateways():
    ipr = IPRoute()
    routes = [dict(r["attrs"]) for r in ipr.get_routes()]
    return [g["RTA_GATEWAY"] for g in routes if "RTA_GATEWAY" in g]
