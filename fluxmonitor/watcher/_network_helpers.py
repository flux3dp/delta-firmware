
from time import sleep
import random
import socket
import json
import os

from fluxmonitor.config import network_config
from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.sys import nl80211


class NetworkMonitorMix(object):
    """ NetworkMonitorMix using linux netlink to monitor network status
    change. Once the network changed, a readable signal will pass to file
    descriptor and call NetworkMonitorMix_on_status_changed method.
    """

    def bootstrap_network_monitor(self, memcache):
        self.nic_status = {}
        self._monitor = Monitor(self._on_status_changed)
        self._on_status_changed(self._monitor.full_status())

        self.rlist += [self._monitor]

    def _on_status_changed(self, status):
        """Callback from self._monitor instance"""
        new_nic_status = {}

        for ifname, data in status.items():
            current_status = self.nic_status.get(ifname, {})
            current_status.update(data)
            new_nic_status[ifname] = current_status

        self.nic_status = new_nic_status
        nic_status = json.dumps(self.nic_status)
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

    # TODO: this is a temp implement that store config in memory
    __CONFIG = {
        "wlan0": {
            "security": "WPA2-PSK", "ssid": "Area51",
            "psk": "3c0cccd4e57d3c82be1f48e298155109"
                   "545b7bf08f41f76a12f34d950b3bc7af",
            "method": "dhcp"}}

    __CONFIG_KEYS = ["method", "ipaddr", "mask", "route", "ns",
                     "ssid", "security", "wepkey", "psk"]

    def set_config(self, ifname, config):
        new_config = {k: v
                      for k, v in config.items() if k in self.__CONFIG_KEYS}

        self.__CONFIG[ifname] = new_config
        return new_config

    def get_config(self, ifname):
        return self.__CONFIG.get(ifname)


class ControlSocketMix(object):
    """ControlSocketMix create a unixsocket (type: dgram) and listen for
    network command.

    Every payload contain a json string: ["task_name", {"my_options": ""}].
    """
    def bootstrap_control_socket(self, memcache):
        self._ctrl_sock = WlanWatcherSocket(self)
        self.rlist += [self._ctrl_sock]

    def bootstrap_nic(self, ifname, delay=0.5, forcus_restart=False):
        """Startup nic, this method will get device information from
        self.nic_status"""

        ifstatus = self.nic_status.get(ifname, {}).get('ifstatus')
        if ifstatus == 'UP':
            if forcus_restart:
                nl80211.ifdown(ifname)
                sleep(delay)
            else:
                return
        elif ifstatus != 'DOWN' or forcus_restart:
            nl80211.ifdown(ifname)
            sleep(delay)

        nl80211.ifup(ifname)

    def is_device_alive(self, ifname):
        """Return if device is UP or not.

        Note: Because wireless device require wpa_supplicant daemon. If
        wpa_supplicant is gone, this method will return False
        """
        if self.nic_status.get(ifname, {}).get('ifstatus') != 'UP':
            return False

        if self.is_wireless(ifname) and \
           not nl80211.ping_wpa_supplicant(ifname):
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

    def on_read(self):
        try:
            buf = self.recv(4096)
            payload = json.loads(buf)
            cmd, data = payload
        except (ValueError, TypeError):
            self.logger.error("Can not process request: %s" % buf)

        if cmd == "config_network":
            self.config_network(data)

    def config_network(self, payload):
        ifname = payload.pop("ifname")
        config = self.master.set_config(ifname, payload)
        self.master.logger.info(
            "Update '%s' config with %s" % (ifname, config))
        self.master.bootstrap(ifname, rebootstrap=True)
