
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

from fluxmonitor import security as S
from fluxmonitor.config import network_config
from fluxmonitor.watcher.flux_upnp import CODE_DISCOVER, \
    CODE_SET_NETWORK, DEFAULT_PORT

from fluxmonitor.watcher.flux_upnp import UpnpWatcher, UpnpSocket


class UpnpServicesMixTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpServicesMix"""

    def setUp(self):
        U.clean_db()
        self.cache = MemcacheTestClient()
        self.server = ServerSimulator()
        self.w = UpnpWatcher(self.server)

    def tearDown(self):
        self.w.shutdown()
        self.w = None

    def test_fetch_rsa_key(self):
        resp = self.w.cmd_rsa_key({})
        self.assertIsNotNone(resp)

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

    def test_change_pwd(self):
        self.assertTrue(S.set_password(self.cache, "fluxmonitor", None))
        S.add_trusted_keyobj(S.get_keyobj(der=U.PUBLICKEY_3))

        # OK
        self.cache.erase()
        req = b"\x00".join((b"new_fluxmonitor", b"fluxmonitor"))
        resp = self.w.cmd_change_pwd(None, req)
        self.assertIn("timestemp", resp)

        # Fail
        self.cache.erase()
        req = b"\x00".join((b"new_fluxmonitor", b"fluxmonitor"))
        self.assertRaises(RuntimeError,
                          self.w.cmd_change_pwd, "XXX", req)

    def test_cmd_set_network(self):
        S.add_trusted_keyobj(S.get_keyobj(der=U.PUBLICKEY_1))

        req = b"\x00".join(("method=dhcp", "ssid=MYSSID",
            "security=WPA2-PSK", "psk=46a1b78481d2424cbfe46f9"
            "e0729346a56386d071afbbe1641c6d4791a37f3ce"))

        us = U.create_unix_socket(network_config['unixsocket'])
        resp = self.w.cmd_set_network(None, req)
        self.assertIn("timestemp", resp)
        self.server.do_loops()  # each_loop will clean buffer

        # ensure data sent or raise exception
        us.recv(4096)


class UpnpWatcherNetworkMonitorMixTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpWatcher"""

    def setUp(self):
        U.clean_db()
        self.cache = MemcacheTestClient()
        self.w = UpnpWatcher(ServerSimulator())

    def tearDown(self):
        self.w.shutdown()
        self.w = None

    def test_socket_status_on_status_changed(self):
        # Test disable socket
        self.w._on_status_changed({})
        self.assertEqual(self.w.ipaddress, [])

        # Test enable socket
        self.w._on_status_changed({'wlan0': {'ipaddr': ['192.168.1.1']}})
        self.assertEqual(self.w.ipaddress, ['192.168.1.1'])

        # Test disable socket
        self.w._on_status_changed({})
        self.assertEqual(self.w.ipaddress, [])

        self.assertIsInstance(self.w.sock, UpnpSocket)


class UpnpSocketTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpSocket"""

    RESPONSE_PAYLOAD = {"model": "flux3dp:1", "serial": "0x00000000",
                        "ip": ["192.168.1.1", 24]}

    hook = lambda self, *args: self.RESPONSE_PAYLOAD
    logger = logging.getLogger()

    def __init__(self, *args, **kw):
        super(UpnpSocketTest, self).__init__(*args, **kw)

        for hook_name in ["cmd_discover", "cmd_rsa_key", "cmd_nopwd_access",
                          "cmd_pwd_access", "cmd_control_status",
                          "cmd_reset_control", "cmd_require_robot",
                          "cmd_change_pwd",
                          "cmd_set_network", "require_robot"]:
            setattr(self, hook_name, self._cmd_hook)

    def _cmd_hook(self, *args):
        return self.hook(*args)

    def setUp(self):
        self.pkey = S.get_private_key()
        self.memcache = MemcacheTestClient()
        self.sock = UpnpSocket(self, "")

    def tearDown(self):
        self.sock.close()
        self.sock = None

    def create_client(self):
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return client

    def is_local_addr(self, addr):
        return addr is None

    def retrieve_message_from_server(self, client_sock):
        """Let self.sock read and process data"""
        while select.select((self.sock, ), (), (), 0.01)[0]:
            self.sock.on_read(self)

        buf, remote = None, (None, None)

        while self.is_local_addr(remote[0]):
            if select.select((client_sock, ), (), (), 0)[0] == []:
                return None, None, (None, None)
            else:
                buf, remote = client_sock.recvfrom(4096)

        payload, signature = buf[2:].split("\x00", 1)
        return payload, signature, remote

    def test_cmd_discover(self):
        client = self.create_client()

        for can_retry in range(2, -1, -1):
            payload = struct.pack("<4s16sB", "FLUX", "\x00"*16, CODE_DISCOVER)
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

    def _create_message(self, keypair, code, timestemp, *args):
        keyobj = S.get_keyobj(pem=keypair[0])

        head = struct.pack("<4s16sB", "FLUX", "\x00"*16, code)
        access_id = binascii.a2b_hex(S.get_access_id(der=keypair[1]))
        body = "\x00".join(args)

        message = struct.pack("<20sf4s", access_id, timestemp, "abc") + body
        signature = keyobj.sign(head[4:20] + message)
        encrypt_message = S.get_private_key().encrypt(message + signature)
        return head + encrypt_message

    def test_cmd_set_network(self):
        S.add_trusted_keyobj(
            S.get_keyobj(der=U.KEYPAIR1[1]))

        client = self.create_client()

        for can_retry in range(2, -1, -1):
            payload = self._create_message(U.KEYPAIR1, CODE_SET_NETWORK,
                                           time(), "HI")
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
