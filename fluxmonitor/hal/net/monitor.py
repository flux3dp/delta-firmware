
import platform
import logging

if platform.system().lower().startswith("linux"):
    from pyroute2 import IPRoute
    from pyroute2.netlink.rtnl import (
        RTNLGRP_IPV4_IFADDR,
        RTNLGRP_LINK, )

    BIND_GROUPS = RTNLGRP_IPV4_IFADDR | RTNLGRP_LINK
else:
    from ._iproute2 import IPRoute
    BIND_GROUPS = 0

logger = logging.getLogger(__name__)


class Monitor(object):
    """Network status change monitor

    Monitor is an event drive network status monitor, it will trigger a read
    signal only if network has any change. This is a netlink API wrapper for
    fluxmonitord watcher. We implement a fake netlink API for darwin."""

    def __init__(self, cb=None):
        self.callback = cb

        self.ipr = IPRoute()
        self.ipr.bind(groups=BIND_GROUPS)

    def fileno(self):
        return self.ipr.fileno()

    # Trigger when self.ipr has data in buffer (Call by event looper)
    def on_read(self, sender):
        # Read all message and drop it. Because it is hard to analyze incomming
        # message, we will query full information and collect it instead.

        for item in self.ipr.get():
            if item.get('event') not in ["RTM_NEWNEIGH", "RTM_NEWROUTE",
                                         "RTM_DELROUTE", "RTM_GETROUTE", ]:
                # Update status only if event is not RTM_NEWNEIGH or we will
                # get many dummy messages.
                status = self.full_status()
                self.callback(status)
                return

    def read(self):
        for change in self.ipr.get():
            if change.get('event') not in ["RTM_NEWNEIGH", "RTM_NEWROUTE",
                                           "RTM_DELROUTE", "RTM_GETROUTE", ]:
                logger.debug("NW EVENT: %s", change["event"])
                return True
        return False

    # Query full network information and collect it to flux internal pattern.
    def full_status(self):
        status = {}

        for nic in self.ipr.get_links():
            info = dict(nic['attrs'])
            ifname = info.get('IFLA_IFNAME', 'lo')
            if ifname.startswith('lo') or ifname.startswith("mon."):
                continue
            ifindex = nic.get('index', -1)
            ifmac = info.get('IFLA_ADDRESS', '??')
            ifstatus = info.get('IFLA_OPERSTATE', '??')
            ifcarrier = info.get('IFLA_CARRIER', 0) == 1

            st = {'ifindex': ifindex, 'ifmac': ifmac, 'ifstatus': ifstatus,
                  'ifcarrier': ifcarrier, 'ipaddr': []}
            status[ifname] = st

        for addr in self.ipr.get_addr():
            info = dict(addr['attrs'])
            ifname = info.get('IFA_LABEL', 'lo')
            ifname = ifname.split(':')[0]
            if ifname in status:
                status[ifname]['ipaddr'].append(
                    [info.get('IFA_ADDRESS', '0.0.0.0'),
                     addr.get('prefixlen', 32)])

        return status

    def get_ipaddresses(self):
        addresses = []
        for addr in self.ipr.get_addr():
            info = dict(addr['attrs'])
            addr = info.get('IFA_ADDRESS')
            if addr and addr != "127.0.0.1" and addr != "::1":
                addresses.append(addr)
        return addresses

    def close(self):
        self.ipr.close()
