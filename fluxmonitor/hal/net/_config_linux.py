
import tempfile
import logging

from pyroute2 import IPRoute

from fluxmonitor.misc import Process
from fluxmonitor.config import network_services

DHCLIENT = network_services['dhclient']
DHCPD = network_services['dhcpd']

__all__ = ["ifup", "ifdown", "config_ipaddr", "config_nameserver",
           "dhcp_client_daemon", "dhcp_server_daemon"]

logger = logging.getLogger(__name__)


def ifup(ifname):
    logger.debug("ifup %s" % ifname)
    ipr = IPRoute()
    index = _find_device_index(ifname, ipr)
    _clean_ipaddr(ifname, index, ipr)

    ipr.link_up(index=index)


def ifdown(ifname):
    ipr = IPRoute()
    index = _find_device_index(ifname, ipr)
    _clean_ipaddr(ifname, index, ipr)

    logger.debug("ifdown %s" % ifname)
    ipr.link_down(index=index)


def dhcp_client_daemon(manager, ifname):
    logger.debug("[%s] Using DHCP" % ifname)
    return Process(manager, [DHCLIENT, "-w", "-d", ifname])


def dhcp_server_daemon(manager, ifname):
    logger.debug("dhcp server for %s" % ifname)
    dhcpd_conf = tempfile.mktemp() + ".dhcpd.conf"
    dhcpd_leases = tempfile.mktemp() + ".leases"

    _write_dhcpd_config(dhcpd_conf)
    with open(dhcpd_leases, "w"):
        pass

    return Process(manager, [DHCPD, "-f", "-cf", dhcpd_conf, "-lf",
                             dhcpd_leases])


def config_ipaddr(ifname, config):
    logger.debug("[%s] ifconfig: %s" % (ifname, config))

    ipr = IPRoute()
    index = _find_device_index(ifname, ipr)

    ipaddr = config["ipaddr"]
    mask = config["mask"]
    route = config.get("route")
    ns = config.get("ns")

    logger.debug("[%s] Add ip %s/%s" % (ifname, ipaddr, mask))
    ipr.addr('add', index=index, address=ipaddr, mask=mask)

    _clean_route()

    if route:
        logger.debug("Add gateway %s" % (route))
        ipr.route('add', gateway=route)

    if ns:
        config_nameserver(ns)


def config_nameserver(nameservers):
    """Config nameserver setting, the params is a list contains multi
    nameserviers"""

    logger.debug("nameserver config %s" % nameservers)

    with open("/etc/resolv.conf", "w") as f:
        f.write("# This file is overwrite by fluxmonitord\n\n")
        for row in nameservers:
            f.write("nameserver %s\n" % row)
        f.close()


# Private Methods
def _find_device_index(ifname, ipr):
    devices = ipr.link_lookup(ifname=ifname)
    if len(devices) == 0:
        raise RuntimeError("Bad ifname %s" % ifname)
    return devices[0]


def _clean_ipaddr(ifname, index, ipr):
    for address, mask in _get_ipaddresses(index):
        try:
            logger.debug("Del ip %s/%s for %s" % (address, mask, ifname))
            ipr.addr('del', index=index, address=address, mask=mask)
        except Exception:
            logger.exception("Remove ipaddr error")


def _clean_route():
    ipr = IPRoute()
    for g in _get_gateways():
        try:
            ipr.route("delete", gateway=g)
        except Exception:
            logger.exception("Remove route error")


def _get_ipaddresses(index):
    ipr = IPRoute()
    return [(i['attrs'][0][1], i['prefixlen'])
            for i in ipr.get_addr()
            if i['index'] == index]


def _get_gateways():
    ipr = IPRoute()
    routes = [dict(r["attrs"]) for r in ipr.get_routes()]
    return [g["RTA_GATEWAY"] for g in routes if "RTA_GATEWAY" in g]


def _write_dhcpd_config(filepath):
    with open(filepath, "w") as f:
        f.write("""# Create by fluxmonitord
default-lease-time 600;
max-lease-time 7200;
log-facility local7;
option routers 192.168.1.1;
option domain-name-servers 192.168.1.1;

subnet 192.168.1.0 netmask 255.255.255.0 {
  range 192.168.1.100 192.168.1.200;
}
""")
