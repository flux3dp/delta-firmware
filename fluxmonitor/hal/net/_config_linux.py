

import tempfile
import logging

logger = logging.getLogger(__name__)

from pyroute2 import IPRoute

from fluxmonitor.misc import Process
from fluxmonitor.misc import linux_configure
from fluxmonitor.config import network_config

DHCLIENT = network_config['dhclient']
DHCPD = network_config['dhcpd']

__all__ = ["ifup", "ifdown", "config_ipaddr", "config_nameserver",
           "dhcp_client_daemon", "dhcp_server_daemon"]


def ifup(ifname):
    index = find_device_index(ifname)
    logger.info("ifup %s" % ifname)
    ipr = IPRoute()
    ipr.link_up(index=index)


def ifdown(ifname):
    index = find_device_index(ifname)
    ipr = IPRoute()

    # Get all ip address and delete it
    for address, mask in get_ipaddresses(index):
        logger.info("Del ip %s/%s for %s" % (address, mask, ifname))
        ipr.addr('del', index=index, address=address, mask=mask)

    logger.info("ifdown %s" % ifname)
    ipr.link_down(index=index)


def dhcp_client_daemon(manager, ifname):
    logger.info("dhcp client for %s" % ifname)
    return Process(manager, [DHCLIENT, "-d", ifname])


def dhcp_server_daemon(manager, ifname):
    logger.info("dhcp server for %s" % ifname)
    dhcpd_conf = tempfile.mktemp() + ".dhcpd.conf"
    dhcpd_leases = tempfile.mktemp() + ".leases"

    linux_configure.dhcpd_config_to_file(dhcpd_conf)
    with open(dhcpd_leases, "w"):
        pass

    return Process(manager, [DHCPD, "-f", "-cf", dhcpd_conf, "-lf",
                             dhcpd_leases])


def config_ipaddr(ifname, config):
    logger.info("ifconfig %s: %s" % (ifname, config))

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

    logger.info("nameserver config %s" % nameservers)

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