
from time import time, sleep
import unittest
import binascii
import logging
import struct
import select
import socket
import json

from tests import _utils as U
from tests._utils.memcache import MemcacheTestClient
from tests._utils.server import ServerSimulator

from fluxmonitor.misc import security as S
from fluxmonitor.config import network_config
from fluxmonitor.watcher.flux_upnp import CODE_DISCOVER, \
    CODE_SET_NETWORK, DEFAULT_PORT

from fluxmonitor.watcher.flux_upnp import UpnpWatcher, UpnpSocket


class UpnpServicesMixTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpServicesMix"""

    def setUp(self):
        U.clean_db()
        self.cache = MemcacheTestClient()
        self.w = UpnpWatcher(ServerSimulator())

    def test_fetch_rsa_key(self):
        resp = self.w.cmd_rsa_key({})
        for key in ["code", "pubkey"]:
            self.assertIn(key, resp)

    def test_nopwd_access(self):
        # User 1, padding
        raw_req = struct.pack("<d%is" % len(U.PUBLICKEY_1),
                              time(), U.PUBLICKEY_1)
        resp = self.w.cmd_nopwd_access(raw_req)
        self.assertEqual(resp["status"], "padding")
        self.assertEqual(resp["access_id"],
                         S.get_access_id(der=U.PUBLICKEY_1))

        # User 1, continue padding
        self.cache.erase()
        raw_req = struct.pack("<d%is" % len(U.PUBLICKEY_1),
                              time(), U.PUBLICKEY_1)
        resp = self.w.cmd_nopwd_access(raw_req)
        self.assertEqual(resp["status"], "padding")

        # User 2, blocked
        self.cache.erase()
        raw_req = struct.pack("<d%is" % len(U.PUBLICKEY_2),
                              time(), U.PUBLICKEY_2)
        resp = self.w.cmd_nopwd_access(raw_req)
        self.assertEqual(resp["status"], "blocking")

        # Give user 1 access privilege
        S.add_trusted_keyobj(S.get_keyobj(der=U.PUBLICKEY_1))
        self.assertTrue(S.is_trusted_remote(der=U.PUBLICKEY_1))

        # User 1, ok
        self.cache.erase()
        raw_req = struct.pack("<d%ss" % len(U.PUBLICKEY_1),
                              time(), U.PUBLICKEY_1)
        resp = self.w.cmd_nopwd_access(raw_req)
        self.assertEqual(resp["status"], "ok")

        # Set password access
        self.cache.erase()
        S.set_password(self.cache, "fluxmonitor", None)
        # User 2, blocked
        raw_req = struct.pack("<d%ss" % len(U.PUBLICKEY_2),
                              time(), U.PUBLICKEY_2)
        resp = self.w.cmd_nopwd_access(raw_req)
        self.assertEqual(resp["status"], "deny")

    def _create_message(self, keypair, timestemp, *args):
        access_id = S.get_access_id(der=keypair[1])
        message = struct.pack("<d", timestemp) + "\x00".join(args)

        keyobj = S.get_keyobj(pem=keypair[0])

        signature = keyobj.sign(message)
        payload = binascii.a2b_hex(access_id) + signature + message

        return S.get_private_key().encrypt(payload)

    def test_change_pwd(self):
        self.assertTrue(S.set_password(self.cache, "fluxmonitor", None))
        S.add_trusted_keyobj(S.get_keyobj(der=U.PUBLICKEY_3))

        # OK
        self.cache.erase()
        req = self._create_message(U.KEYPAIR3, time(),
                                   b"new_fluxmonitor", b"fluxmonitor")
        resp = self.w.cmd_change_pwd(req)
        self.assertEqual(resp["status"], "ok")

        # Fail
        self.cache.erase()
        req = self._create_message(U.KEYPAIR3, time(),
                                   b"new_fluxmonitor", b"fluxmonitor")
        resp = self.w.cmd_change_pwd(req)
        self.assertEqual(resp.get("status"), "error")

    def test_cmd_set_network(self):
        S.add_trusted_keyobj(S.get_keyobj(der=U.PUBLICKEY_1))

        req = self._create_message(
            U.KEYPAIR1, time(), "method=dhcp", "ssid=MYSSID",
            "security=WPA2-PSK", "psk=46a1b78481d2424cbfe46f9"
            "e0729346a56386d071afbbe1641c6d4791a37f3ce")

        us = U.create_unix_socket(network_config['unixsocket'])
        resp = self.w.cmd_set_network(req)
        self.assertEqual(resp["status"], "ok")
        self.w.each_loop()  # each_loop will clean buffer

        # ensure data sent or raise exception
        us.recv(4096)


class UpnpWatcherNetworkMonitorMixTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpWatcher"""

    def setUp(self):
        U.clean_db()
        self.cache = MemcacheTestClient()
        self.w = UpnpWatcher(ServerSimulator())

    def test_socket_status_on_status_changed(self):
        # Test disable socket
        self.w._on_status_changed({})
        self.assertEqual(self.w.ipaddress, [])
        self.assertIsNone(self.w.sock)

        # Test enable socket
        self.w._on_status_changed({'wlan0': {'ipaddr': ['192.168.1.1']}})
        self.assertEqual(self.w.ipaddress, ['192.168.1.1'])
        self.assertIsInstance(self.w.sock, UpnpSocket)

        # Test disable socket
        self.w._on_status_changed({})
        self.assertEqual(self.w.ipaddress, [])
        self.assertIsNone(self.w.sock)


class UpnpSocketTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpSocket"""

    RESPONSE_PAYLOAD = {"model": "flux3dp:1", "serial": "0x00000000",
                        "ip": ["192.168.1.1", 24]}

    hook = lambda self, payload: self.RESPONSE_PAYLOAD
    logger = logging.getLogger()

    def __init__(self, *args, **kw):
        self.pkey = S.get_private_key()
        super(UpnpSocketTest, self).__init__(*args, **kw)

        for hook_name in ["cmd_discover", "cmd_rsa_key", "cmd_nopwd_access",
                          "cmd_change_pwd", "cmd_pwd_access",
                          "cmd_set_network"]:
            setattr(self, hook_name, self._cmd_hook)

    def _cmd_hook(self, payload):
        return self.hook(payload)

    def setUp(self):
        self.memcache = MemcacheTestClient()
        self.sock = UpnpSocket(self)

    def tearDown(self):
        self.sock.close()

    def create_client(self):
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return client

    def is_local_addr(self, addr):
        return addr is None

    def retrieve_message_from_server(self, client_sock):
        """Let self.sock read and process data"""
        while select.select((self.sock, ), (), (), 0)[0]:
            self.sock.on_read()

        buf, remote = None, (None, None)

        while self.is_local_addr(remote[0]):
            if select.select((client_sock, ), (), (), 0)[0] == []:
                return None, None, (None, None)
            else:
                buf, remote = client_sock.recvfrom(4096)

        payload, signature = buf.split("\x00", 1)
        return payload, signature, remote

    def test_cmd_discover(self):
        client = self.create_client()

        for can_retry in range(2, -1, -1):
            payload = struct.pack("<4s16sh", "FLUX", "\x00"*16, CODE_DISCOVER)
            client.sendto(payload, ("255.255.255.255", DEFAULT_PORT))

            msg, sign, remote = self.retrieve_message_from_server(client)

            if msg:
                self.assertEqual(json.loads(msg), self.RESPONSE_PAYLOAD)
                break
            else:
                if can_retry:
                    sleep(0.2)
                else:
                    raise RuntimeError("No response")

        client.close()

    def test_cmd_set_network(self):
        S.add_trusted_keyobj(
            S.get_keyobj(pem=S.get_private_key().export_pubkey_pem()))

        client = self.create_client()

        for can_retry in range(2, -1, -1):
            payload = struct.pack("<4s16sh", "FLUX", "\x00"*16,
                                  CODE_SET_NETWORK)
            client.sendto(payload, ("255.255.255.255", DEFAULT_PORT))

            msg, sign, remote = self.retrieve_message_from_server(client)

            if msg:
                self.assertEqual(json.loads(msg), self.RESPONSE_PAYLOAD)
                break
            else:
                if can_retry:
                    sleep(0.2)
                else:
                    raise RuntimeError("No response")

        client.close()
