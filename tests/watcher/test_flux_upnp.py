
import threading
import unittest
import select
import socket
import json

from tests._utils.memcache import MemcacheTestClient

from fluxmonitor.watcher.flux_upnp import DEFAULT_ADDR, DEFAULT_PORT
from fluxmonitor.watcher.flux_upnp import UpnpWatcher, UpnpSocket

LOCAL_HOSTNAME = socket.gethostname()
LOCAL_IPADDR = socket.gethostbyname(LOCAL_HOSTNAME)


class UpnpWatcherTest(unittest.TestCase):
    def setUp(self):
        self.memcache = MemcacheTestClient()

    def test_on_status_changed(self):
        w = UpnpWatcher(self.memcache)

        w._on_status_changed({})
        self.assertEqual(w.ipaddress, [])
        self.assertIsNone(w.sock)

        w._on_status_changed({'wlan0': {'ipaddr': ['192.168.1.1']}})
        self.assertEqual(w.ipaddress, ['192.168.1.1'])
        self.assertIsInstance(w.sock, UpnpSocket)

        w._on_status_changed({})
        self.assertEqual(w.ipaddress, [])
        self.assertIsNone(w.sock)


class UpnpSocketCmdTest(unittest.TestCase):
    CMD_DISCOVER = {"model": "flux3dp:1", "id": "0x00000000",
                    "ip": ["192.168.1.1"]}

    def setUp(self):
        self.assertEqual(threading.active_count(), 1)
        self.memcache = MemcacheTestClient()
        self.sock = UpnpSocket(self)

    def tearDown(self):
        self.sock.close()

    def create_client(self):
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        client.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        return client

    def process_all_messages(self, client_sock, ttl=0):
        """Let self.sock read and process data"""
        while select.select((self.sock, ), (), (), 0)[0]:
            self.sock.on_read()

        but, remote = None, (None, None)

        while remote[0] != LOCAL_IPADDR:
            if select.select((client_sock, ), (), (), 0)[0] == []:
                raise RuntimeError("Does not recive data")
            buf, remote = client_sock.recvfrom(4096)

        return json.loads(buf), remote

    def cmd_discover(self):
        return self.CMD_DISCOVER

    def test_cmd_discover(self):
        client = self.create_client()
        client.sendto(json.dumps({"request": "discover"}), (DEFAULT_ADDR, DEFAULT_PORT))

        retry = 3
        while retry > 0:
            try:
                payload, remote = self.process_all_messages(client)
                self.assertEqual(payload, self.CMD_DISCOVER)
                break
            except RuntimeError:
                if retry == 0:
                    raise
                else:
                    retry -= 1

        client.close()
