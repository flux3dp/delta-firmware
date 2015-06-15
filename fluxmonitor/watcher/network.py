
from time import time
import logging

logger = logging.getLogger(__name__)

from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix, ConfigMix, ControlSocketMix
from fluxmonitor.hal.nl80211 import config as nl80211_config
from fluxmonitor.hal.net import config as net_config
from fluxmonitor.storage import Storage

FLUX_ST_STARTED = "flux_started"


class NetworkWatcher(WatcherBase, NetworkMonitorMix, ConfigMix,
                     ControlSocketMix):
    def __init__(self, server):
        super(NetworkWatcher, self).__init__(server, logger)

        self.server.POLL_TIMEOUT = 1.0
        self.daemons = {}
        # self.storage = Storage("net")

    def start(self):
        self.bootstrap_network_monitor(self.memcache)
        self.bootstrap_control_socket(self.memcache)

        for ifname in self.nic_status.keys():
            try:
                self.bootstrap(ifname)
            except Exception:
                self.logger.exception("Error while bootstrap %s" % ifname)

    def shutdown(self):
        for ifname, daemons in self.daemons.items():
            for dname, instance in daemons.items():
                instance.kill()

    def each_loop(self):
        self.server.POLL_TIMEOUT = min(self.server.POLL_TIMEOUT * 2, 300.)

    def bootstrap(self, ifname, rebootstrap=False):
        """start network interface and apply its configurations"""

        self.logger.info("[%s] Bootstrap" % ifname)
        self.kill_daemons(ifname)

        self.bootstrap_nic(ifname, forcus_restart=True)

        flux_st = self.config_device(ifname, self.get_config(ifname))
        self.nic_status[ifname]["flux_st"] = flux_st

    def config_device(self, ifname, config):
        """config network device (like ip/routing/dhcp/wifi access)"""
        daemon = self.daemons.get(ifname, {})

        if config:
            if self.is_wireless(ifname):
                daemon['wpa'] = nl80211_config.wlan_managed_daemon(
                    self, ifname, config)
                self.logger.debug("[%s] Set associate with %s" %
                                  (ifname, config['ssid']))

            if config["method"] == "dhcp":
                daemon['dhcpc'] = net_config.dhcp_client_daemon(self, ifname)
                self.logger.debug("[%s] Using DHCP" % ifname)
            else:
                net_config.config_ipaddr(ifname, config)
                self.logger.debug("[%s] IP: %s" %
                                  (ifname, config['ipaddr']))

        elif self.is_wireless(ifname):
            daemon['hostapd'] = nl80211_config.wlan_ap_daemon(self, ifname)
            net_config.config_ipaddr(ifname, {'ipaddr': '192.168.1.1',
                                              'mask': 24})
            daemon['dhcpd'] = net_config.dhcp_server_daemon(self, ifname)
            self.logger.debug("[%s] Wireless is not configured, "
                              "start with ap mode" % ifname)

        self.daemons[ifname] = daemon
        return FLUX_ST_STARTED

    def get_daemon_for(self, daemon):
        """return daemon's network interface name and daemon label

        The first return value is network interface name like: lan0, lan1,
        wlan0, wlan1 etc..
        The second return value will be daemon name define in fluxmonitor
        such like wpa, dhcp.
        If daemon is not in self.daemons, it will return 2 None
        """
        for ifname, daemons in self.daemons.items():
            names = [name for name, instance in daemons.items()
                     if instance == daemon]
            if len(names) > 0:
                return ifname, names[0]

        return None, None

    def on_daemon_closed(self, process):
        """This function will be called when any daemon process is ended.

        If the daemon is ended unexpected, we will re-bootstrap it."""
        ifname, name = self.get_daemon_for(process)
        if ifname and name:
            self.daemons[ifname].pop(name, None)

            if name.startswith("*"):
                return  # A killed process, ignore
            elif self.nic_status[ifname]["flux_st"] == FLUX_ST_STARTED:
                self.logger.error("'%s daemon' (%s) is unexpected "
                                  "terminated. Restart." % (name, process))
                self.bootstrap(ifname)
            else:
                self.logger.info("'%s daemon' (%s) is terminated." %
                                 (name, process))
        else:
            self.logger.debug("A process %s closed but not "
                              "in daemon list" % process)

    def kill_daemons(self, ifname):
        daemons = self.daemons.pop(ifname, None)

        if not daemons:
            return

        killed_daemons = {}

        for name, daemon in daemons.items():
            if name.startswith("*"):
                self.logger.error("[%s] Remove zombie daemon %s" %
                                  (ifname, name))
            else:
                try:
                    self.logger.info("[%s] Kill daemon %s" % (ifname, name))
                    daemon.kill()
                    killed_daemons["*" + name] = daemon
                except Exception:
                    self.logger.exception()

        self.daemons[ifname] = killed_daemons
