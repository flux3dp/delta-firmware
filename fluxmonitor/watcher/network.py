
from time import time
import logging

logger = logging.getLogger(__name__)

from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix, ConfigMix, ControlSocketMix
from fluxmonitor.sys import nl80211

debug_config = {"security": "WPA2-PSK", "ssid": "Area51", "psk": "3c0cccd4e57d3c82be1f48e298155109545b7bf08f41f76a12f34d950b3bc7af"}

FLUX_ST_STARTED = "flux_started"

class NetworkWatcher(WatcherBase, NetworkMonitorMix, ConfigMix, ControlSocketMix):
    # If network run as fatal mode
    _fatal = False
    # If internet accessable
    _connected = False
    # Internet connection up/down at
    timestemp = 0
    # Internet connection up/down at list
    timestemps = None

    def __init__(self, memcache):
        self.logger = logger
        self.POLL_TIMEOUT = 1.0

        super(NetworkWatcher, self).__init__(logger, memcache)

        self.timestemps = []
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
        self.POLL_TIMEOUT = min(self.POLL_TIMEOUT * 2, 300.)
        self.connected = connected = self.try_connected()

        if not connected:
            delta = time() - self.timestemp
            if delta > 86400:
                # delta too large, adjust
                self.timestemp = time()
            elif delta > 1800:
                self.fatal = True

    @property
    def connected(self):
        return self._connected

    @connected.setter
    def connected(self, val):
        if self._connected == val: return
        self._connected = val
        self.logger.info("Internet %s" % (val and "connected" or "disconnect"))
        self.POLL_TIMEOUT = 1.0
        self.timestemp = timestemp = time()
        self.timestemps = [t for t in self.timestemps if 300 > (timestemp - t)]
        self.timestemps.append(timestemp)
        self.memcache.set("internet_access", val)
        self.memcache.set("internet_access_timestemp", timestemp)

        if len(self.timestemps) > 10: self.fatal = True

    @property
    def fatal(self):
        return self._fatal

    @fatal.setter
    def fatal(self, val):
        if self._fatal == val: return
        self._fatal = val

        if val:
            self.logger.error("Fatal mode enabled")
        else:
            self.logger.error("Fatal mode disabled")

    def bootstrap_fatal_mode(self):
        pass

    def bootstrap(self, ifname, rebootstrap=False):
        """start network interface and apply its configurations"""

        if rebootstrap:
            self.logger.debug("Kill all daemon for %s" % ifname)
            daemons = self.daemons.pop(ifname, {})
            for name, daemon in daemons.items():
                try: daemon.kill()
                except Exception as e:
                    self.logger.exception()

        self.logger.debug("Bootstrap interface %s" % ifname)
        self.bootstrap_nic(ifname, forcus_restart=rebootstrap)

        if self.fatal:
            pass
        else:
            flux_st = self.config_device(ifname, self.get_config(ifname))
            self.nic_status[ifname]["flux_st"] = flux_st

    def config_device(self, ifname, config):
        """config network device (like ip/routing/dhcp/wifi access)"""
        daemon = {}

        if config:
            if self.is_wireless(ifname):
                daemon['wpa'] = nl80211.wlan_managed_daemon(self, ifname, config)
                self.logger.debug("Set %s associate with %s" % (ifname, config['ssid']))

            if config["method"] == "dhcp":
                daemon['dhcp'] = nl80211.dhcp_client_daemon(self, ifname)
                self.logger.debug("Set %s with DHCP" % ifname)
            else:
                nl80211.config_ipaddr(ifname, config)
                self.logger.debug("Set %s with %s" % (ifname, config['ipaddr']))

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
