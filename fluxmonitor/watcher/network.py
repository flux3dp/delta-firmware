
from time import time
import logging

logger = logging.getLogger(__name__)

from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix, ControlSocketMix
from fluxmonitor.sys import nl80211

debug_config = {"security": "WPA2-PSK", "ssid": "Area51", "psk": "3c0cccd4e57d3c82be1f48e298155109545b7bf08f41f76a12f34d950b3bc7af"}

FLUX_ST_STARTED = "flux_started"

class NetworkWatcher(WatcherBase, NetworkMonitorMix, ControlSocketMix):
    def __init__(self, memcache):
        self.logger = logger
        self.time_coefficient = 1
        self.POLL_TIMEOUT = 1.0

        # Internet connection up/down at
        self.timestemp = None
        # Internet connection up/down at list
        self.timestemps = []
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
        if self.try_connected():
            if not self.connected:
                # system is just connected to Internet
                self.reset_counter(connected=True)
        else:
            if self.connected:
                # system is just disconnected from Internet
                self.reset_counter(connected=False)

        self.POLL_TIMEOUT = min(self.POLL_TIMEOUT * 2, 300.)

    def reset_counter(self, connected):
        self.POLL_TIMEOUT = 1.0
        self.connected = connected
        self.timestemp = timestemp = time()
        self.timestemps = [t for t in self.timestemps if 600 > (timestemp - t)]
        self.timestemps.append(timestemp)

        if len(self.timestemps) > 10:
            # TODO: Connection unstable
            pass

    def bootstrap(self, ifname, rebootstrap=False):
        if rebootstrap:
            self.logger.debug("Kill all daemon for %s" % ifname)
            daemons = self.daemons.pop(ifname, {})
            for name, daemon in daemons.items():
                daemon.kill()

        self.logger.debug("Bootstrap if %s" % ifname)
        self.bootstrap_nic(ifname, forcus_restart=rebootstrap)
        flux_st = self.config_device(ifname, self.get_config(ifname))
        self.nic_status[ifname]["flux_st"] = flux_st

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
        return FLUX_ST_STARTED

    def get_daemon_for(self, daemon):
        """return daemon's network interface name and daemon label

        The first return value is network interface name like: lan0, lan1, wlan0, wlan1 etc..
        The second return value will be daemon name define in fluxmonitor such like wpa, dhcp.
        If daemon is not in self.daemons, it will return 2 None
        """
        for ifname, daemons in self.daemons.items():
            names = [name for name, instance in daemons.items() if instance == daemon]
            if len(names) > 0:
                return ifname, names[0]

        return None, None

    def on_daemon_closed(self, process):
        """This function will be called when any daemon process is ended.

        If the daemon is ended unexpected, we will re-bootstrap it."""
        ifname, name = self.get_daemon_for(process)
        if ifname and name:
            self.daemons[ifname].pop(name, None)

            if self.nic_status[ifname]["flux_st"] == FLUX_ST_STARTED:
                self.bootstrap(ifname, rebootstrap=True)
                self.logger.error("'%s daemon' (%s) is unexpected terminated." % (name, process))
            else:
                self.logger.info("'%s daemon' (%s) is terminated." % (name, process))
        else:
            self.logger.debug("A process %s closed but not in daemon list" % process)

    def get_config(self, ifname):
        # TODO: 
        return {
            "security": "WPA2-PSK", "ssid": "Area51",
            "psk": "3c0cccd4e57d3c82be1f48e298155109545b7bf08f41f76a12f34d950b3bc7af",
            "method": "dhcp"
        }
