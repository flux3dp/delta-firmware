
import json

from fluxmonitor.config import network_config
from fluxmonitor.hal.net.monitor import Monitor

DEBUG = network_config.get("debug", False)


class NetworkMonitorMix(object):
    """ NetworkMonitorMix using linux netlink to monitor network status
    change. Once the network changed, a readable signal will pass to file
    descriptor and call NetworkMonitorMix_on_status_changed method.
    """

    def bootstrap_network_monitor(self, memcache):
        self.nic_status = {}
        self._monitor = Monitor(self._on_status_changed)
        self._on_status_changed(self._monitor.full_status())

        self.add_read_event(self._monitor)

    def _on_status_changed(self, status):
        """Callback from self._monitor instance"""
        new_nic_status = {}

        for ifname, data in status.items():
            current_status = self.nic_status.get(ifname, {})
            current_status.update(data)
            new_nic_status[ifname] = current_status

        self.nic_status = new_nic_status
        nic_status = json.dumps(self.nic_status)
        if DEBUG:
            self.logger.debug("Status: " + nic_status)
        self.memcache.set("nic_status", nic_status)
