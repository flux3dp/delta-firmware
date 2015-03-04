
import logging
import socket
import json
import os

logger = logging.getLogger(__name__)

from fluxmonitor.config import wlan_config
from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.task import wlan_tasks
from fluxmonitor.misc import AsyncSignal

from .base import WatcherBase

class WlanWatcher(WatcherBase):
    def __init__(self, memcache):
        super(WlanWatcher, self).__init__(logger, memcache)
        self.status = {}
        self.monitor = Monitor(self)
        self.on_status_changed(self.monitor.full_status())

        self.running = True

    def run(self):
        self.sock = WlanWatcherSocket(self)
        self.rlist += [self.monitor, self.sock]

        self.bootstrap()
        super(WlanWatcher, self).run()

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

    def is_wireless(self, ifname):
        return ifname.startswith("wlan")

    def bootstrap(self):
        pass
        # for ifname, status in self.status.items():


class WlanWatcherSocket(socket.socket):
    def __init__(self, master):
        self.master = master

        path = wlan_config['unixsocket']
        try: os.unlink(path)
        except Exception: pass

        super(WlanWatcherSocket, self).__init__(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.bind(path)
        logger.debug("wlan command socket created at: %s" % path)

    def on_read(self):
        try:
            buf = self.recv(4096)
            payload = json.loads(buf)
            cmd, data = payload
        except (ValueError, TypeError) as e:
            logger.error("Can not process request: %s" % buf)

        try:
            if cmd in wlan_tasks.public_tasks:
                getattr(wlan_tasks, cmd)(data)
            else:
                logger.error("Can not process command: %s" % cmd)
        except Exception as error:
            logger.exception("Error while processing cmd: %s" % cmd)
