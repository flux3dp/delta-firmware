
import tempfile
import platform
import logging
import socket
import select
import json
import os

logger = logging.getLogger(__name__)

if platform.system().lower().startswith("linux"):
    from pyroute2 import IPRoute
else:
    from fluxmonitor.misc.fake import IPRoute

from .base import WatcherBase
from fluxmonitor.task import wlan_tasks
from fluxmonitor.misc import AsyncSignal

class WlanWatcher(WatcherBase):
    DEFAULT_SOCKET = os.path.join(tempfile.gettempdir(), ".fluxmonitor-wlan")

    def __init__(self, memcache):
        self.status = {}
        self.sig_pipe = AsyncSignal()
        self.memcache = memcache
        self.ipr = IPRoute()
        self.ipr.bind()
        self.renew_status()

        self.running = True
        super(WlanWatcher, self).__init__()

    def run(self):
        self.bootstrap()

        rlist, wlist, xlist = (self.sig_pipe, self.ipr, self.sock), (), ()
        while self.running:
            rl, wl, xl = select.select(rlist, wlist, xlist, 5.0)
            if self.ipr in rl:
                self.ipr.get()
                self.renew_status()

            if self.sock in rl:
                self.handleCommand()

    def renew_status(self):
        new_status = {}

        for nic in self.ipr.get_links():
            info = dict(nic['attrs'])
            ifname = info.get('IFLA_IFNAME', 'lo')
            if ifname == 'lo': continue
            ifindex = nic.get('index', -1)
            ifmac = info.get('IFLA_ADDRESS', '??')
            ifstatus = info.get('IFLA_OPERSTATE', '??')

            st = self.status.get(ifname, {})
            st.update({'ifindex': ifindex,
                'ifmac': ifmac, 'ifstatus': ifstatus, 'ipaddr': []
            })
            new_status[ifname] = st

        for addr in self.ipr.get_addr():
            info = dict(addr['attrs'])
            ifname = info.get('IFA_LABEL', 'lo')
            ifname = ifname.split(':')[0]
            if ifname in new_status:
                new_status[ifname]['ipaddr'].append(info.get('IFA_ADDRESS', '??'))

        self.status = new_status
        nic_status = json.dumps(self.status)
        logger.debug("Status: " + nic_status)
        self.memcache.set("nic_status", nic_status)

    def bootstrap(self):
        # for ifname, status in self.status.items():
        #     if status.get('bootstrap') != True:
        #
        self.prepare_socket() 

    def prepare_socket(self, path=DEFAULT_SOCKET):
        try: os.unlink(path)
        except Exception: pass

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(path)
        logger.debug("wlan command socket created at: %s" % path)

    def handleCommand(self):
        payload = None

        try:
            buf = self.sock.recv(4096)
            payload = json.loads(buf)
        except (ValueError, TypeError) as e:
            logger.error("Can not process request: %s" % buf)

        cmd = payload.pop('cmd', '')
        try:
            if cmd in wlan_tasks.tasks:
                getattr(wlan_tasks, cmd)(payload)
            else:
                logger.error("Can not process command: %s" % cmd)
        except Exception as error:
            logger.exception("Error while processing cmd: %s" % cmd)

    def shutdown(self, log=None):
        self.running = False
        self.sig_pipe.send()
