
import tempfile
import logging
import socket
import select
import json
import os

logger = logging.getLogger(__name__)

import platform
if platform.system().lower().startswith("linux"):
    from pyroute2 import IPRoute
else:
    from fluxmonitor.misc.fake import IPRoute

from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.task import wlan_tasks
from fluxmonitor.misc import AsyncSignal

from .base import WatcherBase

class WlanWatcher(WatcherBase):
    DEFAULT_SOCKET = os.path.join(tempfile.gettempdir(), ".fluxmonitor-wlan")

    def __init__(self, memcache):
        self.sig_pipe = AsyncSignal()
        self.memcache = memcache
        self.monitor = Monitor(self)
        self.status = {}
        self.on_status_changed(self.monitor.full_status())

        self.running = True
        super(WlanWatcher, self).__init__()

    def run(self):
        self.bootstrap()

        rlist, wlist, xlist = (self.sig_pipe, self.monitor, self.sock), (), ()
        while self.running:
            rl, wl, xl = select.select(rlist, wlist, xlist, 5.0)

            if self.monitor in rl: self.monitor.on_read()
            if self.sock in rl: self.handleCommand()

    # Callback from self.monitor instance
    def on_status_changed(self, status):
        new_collection = {}
        
        for ifname, data in status.items():
            current_status = self.status.get(ifname, {})
            current_status.update(data)
            new_collection[ifname] = current_status

        self.status = new_collection
        nic_status = json.dumps(self.status)
        logger.debug("Status: " + nic_status)
        self.memcache.set("nic_status", nic_status)

    def bootstrap(self):
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
            if cmd in wlan_tasks.public_tasks:
                getattr(wlan_tasks, cmd)(payload)
            else:
                logger.error("Can not process command: %s" % cmd)
        except Exception as error:
            logger.exception("Error while processing cmd: %s" % cmd)

    def shutdown(self, log=None):
        self.running = False
        self.sig_pipe.send()
