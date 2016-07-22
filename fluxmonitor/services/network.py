
from random import randrange
from time import sleep
import logging
import socket
import json
import os

import pyev

from fluxmonitor.hal.nl80211.config import get_wlan_ssid
from fluxmonitor.security._security import get_wpa_psk
from fluxmonitor.hal.net.monitor import Monitor as NetworkMonitor
from fluxmonitor.hal.nl80211 import config as nl80211_config
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.security import get_serial
from fluxmonitor.storage import Storage, Metadata
from fluxmonitor.hal.net import config as net_cfg
from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT
from fluxmonitor.misc import network_config_encoder as NCE  # noqa

from .base import ServiceBase

logger = logging.getLogger(__name__)


def is_nic_ready(nic_status):
    return True if "wlan0" in nic_status else False


def is_network_ready(nic_status):
    addrs = nic_status.get("wlan0", {}).get("ipaddr", [])
    return True if len(addrs) > 0 else False


def is_wireless(ifname):
    return ifname.startswith("wlan")


def create_default_config(ifname):
    if is_wireless(ifname):
        model_id = get_model_id()

        if model_id.startswith("delta"):
            model_id = "Delta"
        ssid = "FLUX %s [%s]" % (model_id, "%4x" % randrange(65536))

        return {
            "method": "internal",
            "wifi_mode": "host",
            "ssid": ssid,
            "security": "WPA2-PSK",
            "psk": get_serial(),
        }
    else:
        return {"method": "dhcp"}


class WirelessNetworkReviewer(object):
    workers = set()

    @classmethod
    def add_reviewer(cls, ifname, old_config, essid, service):
        logger.debug("Trace %s config status", ifname)

        if get_wlan_ssid(ifname):
            b = 6.0
        else:
            b = 3.0

        data = cls(ifname, old_config, service, essid)
        watcher = service.loop.timer(b, 1.5, cls.reviewer, data)
        cls.workers.add(watcher)
        watcher.start()

    @classmethod
    def reviewer(cls, watcher, revent):
        data = watcher.data

        if get_wlan_ssid(data.ifname) == data.essid:
            if data.ok_counter == 9:
                watcher.stop()
                cls.workers.remove(watcher)
                logger.info("%s config accepted", data.ifname)
            else:
                data.ok_counter += 1
                logger.debug("Reviewer OK %i/%i",
                             data.ok_counter, data.er_counter)

        else:
            logger.debug("Reviewer ER %i/%i",
                         data.ok_counter, data.er_counter)
            if data.er_counter > 8 or data.ok_counter > 0:
                logger.info("%s config rejected", data.ifname)

                data.service.apply_config(
                    data.ifname, data.old_config, recoverable=False)

                watcher.stop()
                cls.workers.remove(watcher)
            else:
                data.er_counter += 1

    def __init__(self, ifname, old_config, service, essid):
        self.ifname = ifname
        self.old_config = old_config
        self.service = service
        self.essid = essid

        self.ok_counter = 0
        self.er_counter = 0


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


class NetworkService(ServiceBase, NetworkMonitorMixIn):
    def __init__(self, options):
        super(NetworkService, self).__init__(logger)
        self.cm = Metadata()
        self.activated = (self.cm.wifi_status & 1 == 0)
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

        if self.activated:
            self.startup_all_nic()

    def on_shutdown(self):
        self.nms_watcher.stop()
        self.nms_watcher = None
        self.nms.close()
        self.nms = None
        self.timer_watcher.stop()
        self.timer_watcher = None
        self.shutdown_network_notifier()
        self.shutdown_all_nic()

    def on_activate_changed(self):
        activated = (self.cm.wifi_status & 1) == 0
        if activated is False and self.activated is True:
            self.activated = False
            self.shutdown_all_nic()
        elif activated is True and self.activated is False:
            self.activated = True
            self.startup_all_nic()

    def on_timer(self, watcher, revent):
        st = self.update_network_led()
        if st == watcher.data[1]:
            # Network st not change
            if watcher.data[0] < 15:
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
        else:
            c = create_default_config(ifname)
            self.set_config(ifname, c)
            return c

    def update_network_led(self, host_flag=None):
        """Return True if network is read"""
        if host_flag is not None:
            if host_flag:
                self.cm.wifi_status |= 32
            else:
                self.cm.wifi_status &= ~32

        if is_nic_ready(self.nic_status):
            self.cm.wifi_status &= ~128

            if is_network_ready(self.nic_status):
                self.cm.wifi_status |= 64
            else:
                self.cm.wifi_status &= ~64
        else:
            self.cm.wifi_status |= 128

    def startup_all_nic(self):
        logger.debug("startup all nic")
        for ifname in self.nic_status.keys():
            try:
                self.bootstrap(ifname)
            except Exception:
                logger.exception("Error while bootstrap %s" % ifname)

    def shutdown_all_nic(self):
        logger.debug("shutdown all nic")
        for ifname in self.nic_status.keys():
            self.kill_daemons(ifname)
            net_cfg.ifdown(ifname)

    def bootstrap(self, ifname, rebootstrap=False):
        # start network interface and apply its configurations

        logger.debug("[%s] Bootstrap" % ifname)
        if rebootstrap:
            self.kill_daemons(ifname)

        self.bootstrap_nic(ifname, forcus_restart=True)
        config = self.get_config(ifname)
        assert config
        self.config_device(ifname, config)

    def bootstrap_nic(self, ifname, delay=0.5, forcus_restart=False):
        # Startup nic, this method will get device information from
        # self.nic_status

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

    def apply_config(self, ifname, config, recoverable=False):
        if is_wireless(ifname) and recoverable:
            WirelessNetworkReviewer.add_reviewer(
                ifname=ifname, old_config=self.get_config(ifname),
                essid=config.get("ssid"), service=self)

        config = self.set_config(ifname, config)
        logger.debug(
            "Update '%s' config with %s" % (ifname, config))
        self.bootstrap(ifname, rebootstrap=True)

    def config_device(self, ifname, config):
        """config network device (like ip/routing/dhcp/wifi access)"""
        daemon = self.daemons.get(ifname, {})

        if is_wireless(ifname):
            mode = config.get('wifi_mode')
            if mode == 'client':
                if ifname == "wlan0":
                    self.update_network_led(host_flag=False)
                daemon['wpa'] = nl80211_config.wlan_managed_daemon(
                    self, ifname, config)

            elif mode == 'host':
                if ifname == "wlan0":
                    self.update_network_led(host_flag=True)
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
                self.bootstrap(ifname, rebootstrap=True)
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
                    logger.debug("[%s] Kill daemon %s" % (ifname, name))
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
                elif cmd == "power_change":
                    self.master.on_activate_changed()
                else:
                    self.master.logger.error("Unknow cmd: %s" % cmd)
            else:
                self.master.logger.error("Can not process request: %s" % buf)
                return
        except Exception:
            logger.exception("Unhandle error")

    def config_network(self, payload):
        ifname = payload.pop("ifname")
        self.master.apply_config(ifname, payload, recoverable=True)
