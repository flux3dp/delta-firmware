
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.misc import Process

__all__ = ["ifup", "ifdown", "config_ipaddr", "config_nameserver",
           "dhcp_client_daemon", "dhcp_server_daemon"]


def ifup(ifname):
    logger.info("ifup %s" % ifname)


def ifdown(ifname):
    logger.info("ifdown %s" % ifname)


def dhcp_client_daemon(manager, ifname):
    logger.info("dhcp client for %s" % ifname)
    return Process(manager, ["sleep", "60"])


def dhcp_server_daemon(manager, ifname):
    logger.info("dhcp server for %s" % ifname)
    return Process(manager, ["sleep", "60"])


def config_ipaddr(ifname, config):
    logger.info("ifconfig %s: %s" % (ifname, config))


def config_nameserver(nameservers):
    logger.info("nameserver config %s" % nameservers)
