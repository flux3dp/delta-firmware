
import platform
import logging
import select
import json
import sys

logger = logging.getLogger(__name__)

if platform.system().lower().startswith("linux"):
    from pyroute2 import IPRoute
else:
    from fluxmonitor.misc.fake import IPRoute

from .base import WatcherBase
from fluxmonitor.misc import AsyncSignal

class WlanWatcher(WatcherBase):
    def __init__(self, memcache):
        self.sig_pipe = AsyncSignal()
        self.memcache = memcache
        self.ipr = IPRoute()
        self.ipr.bind()
        self.renew_status()

        self.running = True
        super(WlanWatcher, self).__init__()

    def run(self):
        while self.running:
            rl, wl, xl = select.select((self.sig_pipe, self.ipr), (), (), 5.0)
            if self.ipr in rl:
                self.ipr.get()
                self.renew_status()
            elif not rl:
                pass

    def renew_status(self):
        status = {}

        for nic in self.ipr.get_links():
            info = dict(nic['attrs'])
            ifname = info.get('IFLA_IFNAME', 'lo')
            if ifname == 'lo': continue
            ifindex = nic.get('index', -1)
            ifmac = info.get('IFLA_ADDRESS', '??')
            ifstatus = info.get('IFLA_OPERSTATE', '??')
            status[ifname] = {'ifindex': ifindex, 'ifmac': ifmac,
                'ifstatus': ifstatus, 'ipaddr': []
            }

        for addr in self.ipr.get_addr():
            info = dict(addr['attrs'])
            ifname = info.get('IFA_LABEL', 'lo')
            ifname = ifname.split(':')[0]
            if ifname in status:
                status[ifname]['ipaddr'].append(info.get('IFA_ADDRESS', '??'))

        self.status = status
        nic_status = json.dumps(status)
        logger.debug("Status: " + nic_status)
        self.memcache.set("nic_status", nic_status)

    def shutdown(self, log=None):
        self.running = False
        self.sig_pipe.send()
