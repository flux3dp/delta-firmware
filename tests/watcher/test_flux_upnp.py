
from time import time, sleep
import unittest
import binascii
import struct
import select
import socket
import json

from tests import _utils as U
from tests._utils.memcache import MemcacheTestClient

from fluxmonitor.misc import security as S
from fluxmonitor.config import network_config
from fluxmonitor.watcher.flux_upnp import CODE_DISCOVER, \
    CODE_SET_NETWORK, DEFAULT_PORT


from fluxmonitor.watcher.flux_upnp import UpnpWatcher, UpnpSocket


class UpnpServicesMixTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpServicesMix"""

    def setUp(self):
        U.clean_db()
        self.m = MemcacheTestClient()
        self.w = UpnpWatcher(self.m)

    def test_fetch_rsa_key(self):
        resp = self.w.cmd_rsa_key({})
        for key in ["code", "pubkey"]:
            self.assertIn(key, resp)

    def test_nopwd_access(self):
        # User 1, padding
        raw_req = struct.pack("<d%is" % len(U.PUBLICKEY_1),
                              time(), U.PUBLICKEY_1)
        resp = self.w.cmd_nopwd_access(S.encrypt_msg(raw_req))
        self.assertEqual(resp["status"], "padding")
        self.assertEqual(resp["access_id"],
                         S.get_access_id(U.PUBLICKEY_1))

        # User 1, continue padding
        self.m.erase()
        raw_req = struct.pack("<d%is" % len(U.PUBLICKEY_1),
                              time(), U.PUBLICKEY_1)
        resp = self.w.cmd_nopwd_access(S.encrypt_msg(raw_req))
        self.assertEqual(resp["status"], "padding")

        # User 2, blocked
        self.m.erase()
        raw_req = struct.pack("<d%is" % len(U.PUBLICKEY_2),
                              time(), U.PUBLICKEY_2)
        resp = self.w.cmd_nopwd_access(S.encrypt_msg(raw_req))
        self.assertEqual(resp["status"], "blocking")

        # Give user 1 access privilege
        S.add_trust_publickey(U.PUBLICKEY_1)
        self.assertTrue(S.is_trusted_publickey(U.PUBLICKEY_1))

        # User 1, ok
        self.m.erase()
        raw_req = struct.pack("<d%ss" % len(U.PUBLICKEY_1),
                              time(), U.PUBLICKEY_1)
        resp = self.w.cmd_nopwd_access(S.encrypt_msg(raw_req))
        self.assertEqual(resp["status"], "ok")

        # Set password access
        self.m.erase()
        S.set_password(self.m, "fluxmonitor", None, time())
        # User 2, blocked
        raw_req = struct.pack("<d%ss" % len(U.PUBLICKEY_2),
                              time(), U.PUBLICKEY_2)
        resp = self.w.cmd_nopwd_access(S.encrypt_msg(raw_req))
        self.assertEqual(resp["status"], "deny")

    def _create_message(self, keypair, timestemp, *args):
        access_id = S.get_access_id(keypair[1])
        message = "\x00".join(args)
        signature = S.sign(message, pem=keypair[0])

        header = struct.pack("<20sHd", binascii.a2b_hex(access_id),
                             len(signature), timestemp)
        return S.encrypt_msg(header + signature + message)

    def test_change_pwd(self):
        self.assertTrue(
            S.set_password(self.m, "fluxmonitor", None, time()))
        S.add_trust_publickey(U.PUBLICKEY_3)

        # OK
        self.m.erase()
        req = self._create_message(U.KEYPAIR3, time(),
                                   b"new_fluxmonitor", b"fluxmonitor")
        resp = self.w.cmd_change_pwd(req)
        self.assertEqual(resp["status"], "ok")

        # Fail
        self.m.erase()
        req = self._create_message(U.KEYPAIR3, time(),
                                   b"new_fluxmonitor", b"fluxmonitor")
        resp = self.w.cmd_change_pwd(req)
        self.assertEqual(resp.get("status"), "error")

    def test_cmd_set_network(self):
        S.add_trust_publickey(U.PUBLICKEY_1)

        req = self._create_message(
            U.KEYPAIR1, time(), "method=dhcp", "ssid=MYSSID",
            "security=WPA2-PSK", "psk=46a1b78481d2424cbfe46f9"
            "e0729346a56386d071afbbe1641c6d4791a37f3ce")

        us = U.create_unix_socket(network_config['unixsocket'])
        resp = self.w.cmd_set_network(req)
        self.assertEqual(resp["status"], "ok")

        # ensure data sent or raise exception
        select.select((us,), (), (), 3.)
        us.recv(4096)


class UpnpWatcherNetworkMonitorMixTest(unittest.TestCase):
    """Test fluxmonitor.watcher.flux_upnp.UpnpWatcher"""

    def setUp(self):
        U.clean_db()
        self.m = MemcacheTestClient()
        self.w = UpnpWatcher(self.m)

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
                        "ip": ["192.168.1.1"]}

    hook = lambda self, payload: self.RESPONSE_PAYLOAD

    def __init__(self, *args, **kw):
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
            else:
                if can_retry:
                    sleep(0.5)
                else:
                    raise RuntimeError("No response")

        client.close()

    def test_cmd_set_network(self):
        access_id = S.add_trust_publickey(S.get_publickey())

        client = self.create_client()

        for can_retry in range(2, -1, -1):
            payload = struct.pack("<4s16sh", "FLUX", "\x00"*16,
                                  CODE_SET_NETWORK)
            client.sendto(payload, ("255.255.255.255", DEFAULT_PORT))

            msg, sign, remote = self.retrieve_message_from_server(client)

            if msg:
                S.validate_signature(msg, sign, access_id)
                self.assertEqual(json.loads(msg), self.RESPONSE_PAYLOAD)
                break
            else:
                if can_retry:
                    sleep(0.1)
                else:
                    raise RuntimeError("No response")

        client.close()
