
from time import sleep
import random
import socket
import json
import os

from fluxmonitor.misc import network_config_encoder as NCE
from fluxmonitor.hal.net import config as net_config
from fluxmonitor.config import network_config
from fluxmonitor.hal.net.monitor import Monitor
from fluxmonitor.storage import Storage

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

    def is_wireless(self, ifname):
        return ifname.startswith("wlan")

    __AVAILABLE_REMOTES = [
        ("8.8.8.8", 53),  # Google DNS
        ("8.8.4.4", 53),  # Google DNS
        ("168.95.1.1", 53),  # Hinet DNS
        ("198.41.0.4", 53),  # a.root-servers.org
        ("192.228.79.201", 53),  # b.root-servers.org
        ("199.7.91.13", 53),  # d.root-servers.org
    ]

    def __available_remote(self):
        return random.choice(self.__AVAILABLE_REMOTES)

    def try_connected(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(10.)
            s.connect(self.__available_remote())
            s.shutdown(socket.SHUT_RDWR)
            self.memcache.set("network", "1")
            return True
        except Exception as error:
            if not isinstance(self, socket.timeout):
                self.logger.error("Try internet access error: %s" % error)
            self.memcache.set("network", "0")
            return False
        finally:
            s.close()


class ConfigMix(object):
    """ConfigMix provide get/set network config"""

    _storage = None
    @property
    def storage(self):
        if not self._storage:
            self._storage = Storage("net")
        return self._storage

    def set_config(self, ifname, config):
        config = NCE.validate_options(config)
        try:
            with self.storage.open(ifname, "w") as f:
                json.dump(config, f)
        except Exception:
            self.logger.exception("Write network config error")
        return config

    def get_config(self, ifname):
        if self.storage.exists(ifname):
            try:
                with self.storage.open(ifname, "r") as f:
                    return json.load(f)
            except Exception:
                self.logger.exception("Read network config error")
        return None


class ControlSocketMix(object):
    """ControlSocketMix create a unixsocket (type: dgram) and listen for
    network command.

    Every payload contain a json string: ["task_name", {"my_options": ""}].
    """
    def bootstrap_control_socket(self, memcache):
        self._ctrl_sock = WlanWatcherSocket(self)
        self.add_read_event(self._ctrl_sock)

    def bootstrap_nic(self, ifname, delay=0.5, forcus_restart=False):
        """Startup nic, this method will get device information from
        self.nic_status"""

        ifstatus = self.nic_status.get(ifname, {}).get('ifstatus')
        if ifstatus == 'UP':
            if forcus_restart:
                net_config.ifdown(ifname)
                sleep(delay)
            else:
                return
        elif ifstatus != 'DOWN' or forcus_restart:
            net_config.ifdown(ifname)
            sleep(delay)

        net_config.ifup(ifname)

    def is_device_alive(self, ifname):
        """Return if device is UP or not.

        Note: Because wireless device require wpa_supplicant daemon. If
        wpa_supplicant is gone, this method will return False
        """
        if self.nic_status.get(ifname, {}).get('ifstatus') != 'UP':
            return False

        return True

    def is_device_carrier(self, ifname):
        """Return True if wireless is associated or cable plugged"""
        return self.nic_status.get(ifname, {}).get("ifcarrier", None)


class WlanWatcherSocket(socket.socket):
    def __init__(self, master):
        self.master = master

        path = network_config['unixsocket']
        try:
            os.unlink(path)
        except Exception:
            pass

        super(WlanWatcherSocket, self).__init__(socket.AF_UNIX,
                                                socket.SOCK_DGRAM)
        self.bind(path)
        os.chmod(path, 0666)
        self.master.logger.debug(
            "network command socket created at: %s" % path)

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