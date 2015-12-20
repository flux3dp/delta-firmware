
from time import sleep
import logging
import socket
import json
import os

import pyev

from fluxmonitor.security._security import get_wpa_psk
from fluxmonitor.hal.nl80211 import config as nl80211_config
from fluxmonitor.hal.net.monitor import Monitor as NetworkMonitor
from fluxmonitor.storage import Storage, CommonMetadata
from fluxmonitor.hal.net import config as net_cfg
from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT
from fluxmonitor.misc import network_config_encoder as NCE

from .base import ServiceBase

logger = logging.getLogger(__name__)


def is_nic_ready(nic_status):
    return True if "wlan0" in nic_status else False


def is_network_ready(nic_status):
    addrs = nic_status.get("wlan0", {}).get("ipaddr", [])
    return True if len(addrs) > 0 else False


class NetworkConfigMixIn(object):
    """Part of NetworkService

    Provide get and set network config functions"""

    @property
    def storage(self):
        return Storage("net")

    def set_config(self, ifname, config):
        config = NCE.validate_options(config)

        # Encrypt password in client mode
        if "psk" in config and "ssid" in config:
            if config.get("wifi_mode") == "client":
                plain_passwd = config["psk"]
                config["psk"] = get_wpa_psk(config["ssid"], plain_passwd)

        try:
            with self.storage.open(ifname, "w") as f:
                json.dump(config, f)
        except Exception:
            logger.exception("Write network config error")
        return config

    def get_config(self, ifname):
        if self.storage.exists(ifname):
            try:
                with self.storage.open(ifname, "r") as f:
                    return json.load(f)
            except Exception:
                logger.exception("Read network config error")
        return None


class NetworkMonitorMixIn(object):
    """Monitor NIC status changed event from system"""

    def start_network_notifier(self):
        self._network_notifier = NetworkMonitor()
        self._network_notifier_watcher = self.loop.io(
            self._network_notifier, pyev.EV_READ, self._on_network_changed)
        self._network_notifier_watcher.start()

        self.update_nic_status()

    def shutdown_network_notifier(self):
        self._network_notifier_watcher.stop()
        self._network_notifier_watcher = None
        self._network_notifier.close()
        self._network_notifier = None

    def _on_network_changed(self, watcher, revent):
        if self._network_notifier.read():
            self.update_nic_status()

    def update_nic_status(self, status=None):
        if not status:
            status = self._network_notifier.full_status()

        new_nic_status = {}

        for ifname, data in status.items():
            current_status = self.nic_status.get(ifname, {})
            current_status.update(data)
            new_nic_status[ifname] = current_status

        self.nic_status = new_nic_status
        nic_status = json.dumps(self.nic_status)
        self.logger.debug("Status Changed: " + nic_status)


class NetworkService(ServiceBase, NetworkConfigMixIn, NetworkMonitorMixIn):
    def __init__(self, options):
        super(NetworkService, self).__init__(logger)
        self.cm = CommonMetadata()
        self.nic_status = {}
        self.daemons = {}

        self.timer_watcher = self.loop.timer(0, 5, self.on_timer, (5, None))
        self.timer_watcher.start()

    def on_start(self):
        self.nms = nms = NetworkManageSocket(self)
        self.nms_watcher = self.loop.io(nms, pyev.EV_READ, nms.on_message,
                                        nms)
        self.nms_watcher.start()
        self.start_network_notifier()

        for ifname in self.nic_status.keys():
            try:
                self.bootstrap(ifname)
            except Exception:
                logger.exception("Error while bootstrap %s" % ifname)

    def on_shutdown(self):
        self.nms_watcher.stop()
        self.nms_watcher = None
        self.nms.close()
        self.nms = None
        self.shutdown_network_notifier()

        for ifname, daemons in self.daemons.items():
            for dname, instance in daemons.items():
                instance.kill()

    def on_timer(self, watcher, revent):
        st = self.update_network_led()
        if st == watcher.data[1]:
            # Network st not change
            if watcher.data[0] < 30:
                g = watcher.data[0]
                watcher.stop()
                watcher.set(g + 2, g + 2)
                watcher.reset()
                watcher.data = (g + 2, st)
                watcher.start()

        else:
            watcher.stop()
            watcher.set(5, 5)
            watcher.reset()
            watcher.data = (5, st)
            watcher.start()

    def update_network_led(self):
        """Return True if network is read"""
        if is_nic_ready(self.nic_status):
            self.cm.wifi_status &= ~128
            if is_network_ready(self.nic_status):
                self.cm.wifi_status |= 64
                return True
            else:
                self.cm.wifi_status &= ~64
                return False
        else:
            self.cm.wifi_status |= 128

    def bootstrap(self, ifname, rebootstrap=False):
        """start network interface and apply its configurations"""

        logger.info("[%s] Bootstrap" % ifname)
        self.kill_daemons(ifname)

        self.bootstrap_nic(ifname, forcus_restart=True)

        config = self.get_config(ifname)
        if config:
            self.config_device(ifname, config)

    def bootstrap_nic(self, ifname, delay=0.5, forcus_restart=False):
        """Startup nic, this method will get device information from
        self.nic_status"""

        ifstatus = self.nic_status.get(ifname, {}).get('ifstatus')
        if ifstatus == 'UP':
            if forcus_restart:
                net_cfg.ifdown(ifname)
                sleep(delay)
            else:
                return
        elif ifstatus != 'DOWN' or forcus_restart:
            net_cfg.ifdown(ifname)
            sleep(delay)

        net_cfg.ifup(ifname)

    def is_wireless(self, ifname):
        return ifname.startswith("wlan")

    def config_device(self, ifname, config):
        """config network device (like ip/routing/dhcp/wifi access)"""
        daemon = self.daemons.get(ifname, {})

        if self.is_wireless(ifname):
            mode = config.get('wifi_mode')
            if mode == 'client':
                daemon['wpa'] = nl80211_config.wlan_managed_daemon(
                    self, ifname, config)

            elif mode == 'host':
                daemon['hostapd'] = nl80211_config.wlan_ap_daemon(
                    self, ifname, config)
                net_cfg.config_ipaddr(ifname,
                                      {'ipaddr': '192.168.1.1', 'mask': 24,
                                       'route': '192.168.1.254'})

        if config["method"] == "dhcp":
            daemon['dhcpc'] = net_cfg.dhcp_client_daemon(self, ifname)
        elif config["method"] == "internal":
            daemon['dhcpd'] = net_cfg.dhcp_server_daemon(self, ifname)
        elif config["method"] == "static":
            net_cfg.config_ipaddr(ifname, config)

        self.daemons[ifname] = daemon

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
            else:
                logger.error("'%s daemon' (%s) is unexpected "
                             "terminated. Restart." % (name, process))
                self.bootstrap(ifname)
        else:
            logger.error("A process %s closed but not "
                         "in daemon list" % process)

    def kill_daemons(self, ifname):
        daemons = self.daemons.pop(ifname, None)

        if not daemons:
            return

        killed_daemons = {}

        for name, daemon in daemons.items():
            if name.startswith("*"):
                logger.error("[%s] Remove zombie daemon %s" % (ifname, name))
            else:
                try:
                    logger.info("[%s] Kill daemon %s" % (ifname, name))
                    daemon.kill()
                    killed_daemons["*" + name] = daemon
                except Exception:
                    logger.exception()

        self.daemons[ifname] = killed_daemons


class NetworkManageSocket(socket.socket):
    def __init__(self, master):
        self.master = master

        path = NETWORK_MANAGE_ENDPOINT
        try:
            os.unlink(path)
        except Exception:
            pass

        super(NetworkManageSocket, self).__init__(socket.AF_UNIX,
                                                  socket.SOCK_DGRAM)
        self.bind(path)
        os.chmod(path, 0666)
        self.master.logger.debug(
            "network manage socket created at: %s" % path)

    def on_message(self, watcher, revent):
        try:
            buf = self.recv(4096)
            payloads = buf.split("\x00", 1)

            if len(payloads) == 2:
                cmd, data = payloads
                if cmd == "config_network":
                    self.config_network(NCE.parse_bytes(data))
                else:
                    self.master.logger.error("Unknow cmd: %s" % cmd)
            else:
                self.master.logger.error("Can not process request: %s" % buf)
                return
        except Exception:
            logger.exception("Unhandle error")

    def config_network(self, payload):
        ifname = payload.pop("ifname")
        config = self.master.set_config(ifname, payload)
        self.master.logger.info(
            "Update '%s' config with %s" % (ifname, config))
        self.master.bootstrap(ifname, rebootstrap=True)
