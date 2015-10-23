
from time import sleep
import logging
import socket
import json
import os

from fluxmonitor.security._security import get_wpa_psk
from fluxmonitor.hal.nl80211 import config as nl80211_config
from fluxmonitor.hal.net.monitor import Monitor as NetworkNotifier
from fluxmonitor.storage import Storage, CommonMetadata
from fluxmonitor.hal.net import config as net_configure
from fluxmonitor.config import network_config
from fluxmonitor.misc import network_config_encoder as NCE

from .base import ServiceBase

logger = logging.getLogger(__name__)
FLUX_ST_STARTED = "flux_started"


def is_nic_ready(nic_status):
    return True if "wlan0" in nic_status else False


def is_network_ready(nic_status):
    addrs = nic_status.get("wlan0", {}).get("ipaddr", [])
    return True if len(addrs) > 0 else False


class NetworkConfigMixin(object):
    """Part of NetworkService

    Provide get and set network config functions"""

    @property
    def storage(self):
        return Storage("net")

    def set_config(self, ifname, config):
        config = NCE.validate_options(config)

        # Encrypt password
        if "psk" in config and "ssid" in config:
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


class NetworkNotifierMixIn(object):
    """Monitor NIC status changed event from system"""

    def start_network_notifier(self):
        self._network_notifier = NetworkNotifier(self.update_nic_status)
        self.add_read_event(self._network_notifier)
        self.update_nic_status()

    def shutdown_network_notifier(self):
        self.remove_read_event(self._network_notifier)

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


class NetworkService(ServiceBase, NetworkConfigMixin, NetworkNotifierMixIn):
    def __init__(self, options):
        super(NetworkService, self).__init__(logger)
        self.cm = CommonMetadata()
        self.nic_status = {}
        self.daemons = {}

    def on_start(self):
        self.nms = NetworkManageSocket(self)
        self.add_read_event(self.nms)
        self.start_network_notifier()

        for ifname in self.nic_status.keys():
            try:
                self.bootstrap(ifname)
            except Exception:
                logger.exception("Error while bootstrap %s" % ifname)

    def on_shutdown(self):
        self.remove_read_event(self.nms)
        self.nms.close()
        self.shutdown_network_notifier()

        for ifname, daemons in self.daemons.items():
            for dname, instance in daemons.items():
                instance.kill()

    def each_loop(self):
        if is_nic_ready(self.nic_status):
            self.cm.wifi_status &= ~128
            if is_network_ready(self.nic_status):
                self.cm.wifi_status |= 64
            else:
                self.cm.wifi_status &= ~64
        else:
            self.cm.wifi_status |= 128

    def bootstrap(self, ifname, rebootstrap=False):
        """start network interface and apply its configurations"""

        logger.info("[%s] Bootstrap" % ifname)
        self.kill_daemons(ifname)

        self.bootstrap_nic(ifname, forcus_restart=True)

        flux_st = self.config_device(ifname, self.get_config(ifname))
        self.nic_status[ifname]["flux_st"] = flux_st

    def bootstrap_nic(self, ifname, delay=0.5, forcus_restart=False):
        """Startup nic, this method will get device information from
        self.nic_status"""

        ifstatus = self.nic_status.get(ifname, {}).get('ifstatus')
        if ifstatus == 'UP':
            if forcus_restart:
                net_configure.ifdown(ifname)
                sleep(delay)
            else:
                return
        elif ifstatus != 'DOWN' or forcus_restart:
            net_configure.ifdown(ifname)
            sleep(delay)

        net_configure.ifup(ifname)

    def is_wireless(self, ifname):
        return ifname.startswith("wlan")

    def config_device(self, ifname, config):
        """config network device (like ip/routing/dhcp/wifi access)"""
        daemon = self.daemons.get(ifname, {})

        if config:
            if self.is_wireless(ifname):
                daemon['wpa'] = nl80211_config.wlan_managed_daemon(
                    self, ifname, config)
                logger.debug("[%s] Set associate with %s" %
                             (ifname, config['ssid']))

            if config["method"] == "dhcp":
                daemon['dhcpc'] = net_configure.dhcp_client_daemon(self,
                                                                   ifname)
                logger.debug("[%s] Using DHCP" % ifname)
            else:
                net_configure.config_ipaddr(ifname, config)
                logger.debug("[%s] IP: %s" % (ifname, config['ipaddr']))

        elif self.is_wireless(ifname):
            daemon['hostapd'] = nl80211_config.wlan_ap_daemon(self, ifname)
            net_configure.config_ipaddr(ifname, {'ipaddr': '192.168.1.1',
                                        'mask': 24})
            daemon['dhcpd'] = net_configure.dhcp_server_daemon(self, ifname)
            logger.debug("[%s] Wireless is not configured, "
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
                logger.error("'%s daemon' (%s) is unexpected "
                             "terminated. Restart." % (name, process))
                self.bootstrap(ifname)
            else:
                logger.info("'%s daemon' (%s) is terminated." %
                            (name, process))
        else:
            logger.debug("A process %s closed but not "
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

        path = network_config['unixsocket']
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

    def on_read(self, sender):
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

    def config_network(self, payload):
        ifname = payload.pop("ifname")
        config = self.master.set_config(ifname, payload)
        self.master.logger.info(
            "Update '%s' config with %s" % (ifname, config))
        self.master.bootstrap(ifname, rebootstrap=True)


# class NetworkMonitor(object):
#     """A sub-thread process to monitor wifi ssid and internet access status.
#
#     Please note that this class will use multi-thread.
#     """
#
#     def __init__(self):
#         from threading import Thread
#         self.thread = Thread(target=self.__thread_entry__)
#         self.thread.daemon = True
#
#         self.running = True
#         self.thread.start()
#
#     def close(self):
#         self.running = False
#
#     def __thread_entry__(self):
#         from time import sleep
#
#         # while self.running:
#         #
#
