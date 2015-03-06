
import logging

logger = logging.getLogger(__name__)

from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix, ControlSocketMix, NetworkDetector
from fluxmonitor.sys import nl80211

debug_config = {"security": "WPA2-PSK", "ssid": "Area51", "psk": "3c0cccd4e57d3c82be1f48e298155109545b7bf08f41f76a12f34d950b3bc7af"}

class NetworkWatcher(WatcherBase, NetworkMonitorMix, ControlSocketMix,
        NetworkDetector):
    def __init__(self, memcache):
        self.logger = logger
        self.time_coefficient = 1
        self.POLL_TIMEOUT = 1.0
        self.connected = False
        super(NetworkWatcher, self).__init__(logger, memcache)

        self.daemons = {}
        self.bootstrap_network_monitor(memcache)
        self.bootstrap_control_socket(memcache)

    def run(self):
        for ifname in self.nic_status.keys(): self.bootstrap(ifname)
        super(NetworkWatcher, self).run()

        for ifname, daemons in self.daemons:
            for dname, instance in daemons:
                instance.kill()

    def each_loop(self):
        pass

    def bootstrap(self, ifname, rebootstrap=False):
        if rebootstrap:
            self.logger.debug("Kill all daemon for %s" % ifname)
            daemons = self.daemons.pop(ifname, {})
            for name, daemon in daemons.items():
                daemon.kill()

        self.logger.debug("Bootstrap if %s" % ifname)
        self.bootstrap_nic(ifname, forcus_restart=rebootstrap)

        for ifname in self.nic_status.keys():
            self.config_device(ifname, self.get_config(ifname))

    def config_device(self, ifname, config):
        daemon = {}

        if config:
            if self.is_wireless(ifname):
                daemon['wpa'] = nl80211.wlan_managed_daemon(self, ifname, config)
                self.logger.debug("Set %s associate with %s" % (ifname, config['ssid']))

            if config["method"] == "dhcp":
                daemon['dhcp'] = nl80211.dhcp_client_daemon(self, ifname)
                self.logger.debug("Set %s with DHCP" % ifname)
            else:
                nl80211.config_ipaddr(self, ifname, config)
                self.logger.debug("Set %s with %s" % (ifname, config['address']))

        elif self.is_wireless(ifname):
            daemon['hostapd'] = nl80211.wlan_ap_daemon(self, ifname)
            self.logger.debug("Wireless %s not configured, start with ap mode" % ifname)

        self.daemons[ifname] = daemon

    def on_daemon_closed(self, process):
        for ifname, daemons in self.daemons.items():
            names = [name for name, instance in daemons.items() if instance == process]
            if len(names) > 0:
                name = names[0]
                daemons.pop(name)
                self.logger.error("'%s daemon' (%s) is unexpected terminated." % (name, process.cmd))
                self.bootstrap(ifname, rebootstrap=True)

    def get_config(self, ifname):
        return {
            "security": "WPA2-PSK", "ssid": "Area51",
            "psk": "3c0cccd4e57d3c82be1f48e298155109545b7bf08f41f76a12f34d950b3bc7af",
            "method": "dhcp"
        }
