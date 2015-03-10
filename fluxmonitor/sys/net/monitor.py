
import platform
if platform.system().lower().startswith("linux"):
    from pyroute2 import IPRoute
else:
    from fluxmonitor.sys.net._iproute2 import IPRoute


class Monitor(object):
    """Network status change monitor

    Monitor is an event drive network status monitor, it will trigger a read
    signal only if network has any change. This is a netlink API wrapper for
    fluxmonitord watcher. We implement a fake netlink API for darwin."""

    def __init__(self, cb):
        self.callback = cb

        self.ipr = IPRoute()
        self.ipr.bind()

    def fileno(self):
        return self.ipr.fileno()

    # Trigger when self.ipr has data in buffer (Call by event looper)
    def on_read(self):
        # Read all message and drop it. Because it is hard to analyze incomming
        # message, we will query full information and collect it instead.

        for item in self.ipr.get():
            if item.get('event') != "RTM_NEWNEIGH":
                # Update status only if event is not RTM_NEWNEIGH or we will
                # get many dummy messages.
                status = self.full_status()
                self.callback(status)
                return

    # Query full network information and collect it to flux internal pattern.
    def full_status(self):
        status = {}

        for nic in self.ipr.get_links():
            info = dict(nic['attrs'])
            ifname = info.get('IFLA_IFNAME', 'lo')
            if ifname == 'lo' or ifname.startswith("mon."):
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
                status[ifname]['ipaddr'].append(info.get('IFA_ADDRESS', '??'))

        return status
