
import logging

logger = logging.getLogger(__name__)

from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix, ControlSocketMix, NetworkDetector

class NetworkWatcher(WatcherBase, NetworkMonitorMix, ControlSocketMix,
        NetworkDetector):
    def __init__(self, memcache):
        self.logger = logger
        self.time_coefficient = 1
        self.POLL_TIMEOUT = 1.0
        self.connected = False
        super(NetworkWatcher, self).__init__(logger, memcache)

        self.bootstrap_network_monitor(memcache)
        self.bootstrap_control_socket(memcache)

    def run(self):
        self.connected = self.try_connected()
        self.logger.debug("Network %s" % ("connected" if self.connected else "DISCONNECTED",))
        super(NetworkWatcher, self).run()

    def each_loop(self):
        pass

    @property
    def network_configured(self):
        return self.memcache.get("network_mode") == "adhoc"

    @property
    def is_adhoc(self):
        return self.memcache.get("network_mode") == "adhoc"
