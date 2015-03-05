
from time import sleep
import random
import socket
import json
import os

from fluxmonitor.config import network_config
from fluxmonitor.sys.net.monitor import Monitor
from fluxmonitor.sys import nl80211
from fluxmonitor.task import network_tasks

from .base import WatcherBase

class NetworkDetector(object):
    """ try_connected() will tell you if internet access is available."""

    __AVAILABLE_REMOTES = [
        ("8.8.8.8", 53), # Google DNS
        ("8.8.4.4", 53), # Google DNS
        ("168.95.1.1", 53), # Hinet DNS
        ("198.41.0.4", 53), # a.root-servers.org
        ("192.228.79.201", 53), # b.root-servers.org
        ("199.7.91.13", 53), # d.root-servers.org
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

class ControlSocketMix(object):
    """ControlSocketMix create a unixsocket (type: dgram) and listen for
    network command. Look at `fluxmonitor.task.network_tasks` to see what
    command you can use.
    
    Every payload contain a json string: ["task_name", {"my_options": ""}].
    """
    def bootstrap_control_socket(self, memcache):
        self._ctrl_sock = WlanWatcherSocket(self)
        self.rlist += [self._ctrl_sock]

    def bootstrap_nic(self, delay=0.5, forcus_restart=False):
        """Startup nic, this method will get all device information from
        self.nic_status"""

        start_list = []
        if forcus_restart:
            for ifname in self.nic_status.keys():
                nl80211.ifdown(ifname)
                start_list.append(ifname)
        else:
            for ifname, ifstatus in self.nic_status.items():
                if ifstatus.get('ifstatus') != 'UP':
                    # Shut it down anyway to prevent any possible issue
                    nl80211.ifdown(ifname)
                    start_list.append(ifname)

        sleep(delay)
        for ifname in start_list: nl80211.ifup(ifname)

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
        #TODO: as you see ^_^
        return True

class WlanWatcherSocket(socket.socket):
    def __init__(self, master):
        self.master = master

        path = network_config['unixsocket']
        try: os.unlink(path)
        except Exception: pass

        super(WlanWatcherSocket, self).__init__(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.bind(path)
        self.master.logger.debug("network command socket created at: %s" % path)

    def on_read(self):
        try:
            buf = self.recv(4096)
            payload = json.loads(buf)
            cmd, data = payload
        except (ValueError, TypeError) as e:
            self.logger.error("Can not process request: %s" % buf)

        try:
            if cmd in network_tasks.public_tasks:
                getattr(network_tasks, cmd)(data)
            else:
                self.logger.error("Can not process command: %s" % cmd)
        except Exception as error:
            self.logger.exception("Error while processing cmd: %s" % cmd)

