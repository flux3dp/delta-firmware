
import logging
import socket
import json
import os

logger = logging.getLogger(__name__)

from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.task import wlan_tasks
from fluxmonitor.misc import AsyncSignal

from .base import WatcherBase

class NetworkWatcher(WatcherBase):
    def __init__(self, memcache):
        super(WlanWatcher, self).__init__(logger, memcache)

    def run(self):
        self.is_connected()
        super(NetworkWatcher, self).run()

    def each_loop(self):
        pass

    def is_connected(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(10.)
            s.connect(("8.8.8.8", 53))
            s.shutdown(socket.SHUT_RDWR)
            return True
        except socket.timeout as error: pass
        except Exception as error:
            logger.error("Try internet access error: %s" % error)
            return False
        finally:
            s.close()
