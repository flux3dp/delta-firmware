
from select import select
import unittest
import msgpack
import socket
import pyev

from fluxmonitor.interfaces.cloud import CloudUdpSyncHander
from fluxmonitor.services.cloud import Session
from fluxmonitor.security import RSAObject

SERVER_PKEY = RSAObject(keylength=1024)
DEVICE_PKEY = RSAObject(keylength=1024)
SESSION_KEY_HEX = "00000001"
SESSION_KEY = b"\x00\x00\x00\x01"
session = Session(SESSION_KEY_HEX, 3600,
                  RSAObject(der=SERVER_PKEY.export_pubkey_der()),
                  DEVICE_PKEY)


class TestCloudUdpSyncHander(unittest.TestCase):
    call_history = []

    def setUp(self):
        self.call_history = []
        self.serv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.serv_sock.bind(("127.0.0.1", 0))
        self.serv_sock.setblocking(False)
        self.loop = pyev.Loop()
        self.handler = CloudUdpSyncHander(
            kernel=self, endpoint=self.serv_sock.getsockname(), timestemp=0,
            session=session)

    def tearDown(self):
        self.handler = None
        self.loop = None
        self.serv_sock.close()
        self.serv_sock = None

    def require_camera(self, camera_id, endpoint, token):
        self.call_history.append(
            ("require_camera", camera_id, endpoint, token))

    def test_udp_sync_send(self):
        self.handler.send(b"BALABALA")
        select((self.serv_sock, ), (), (), 0.1)
        buf = self.serv_sock.recv(4096)

        keysize = len(SESSION_KEY)
        self.assertEqual(buf[:keysize], SESSION_KEY)
        self.assertEqual(SERVER_PKEY.decrypt(buf[keysize:]), b"BALABALA")

    def test_udp_handle_push_message(self):
        self.handler.on_message(b"\x00", self.serv_sock.getsockname())

    def test_udp_handle_request_message(self):
        # (timestemp, action id, camera id, endpoint, token)
        req = msgpack.packb((self.handler.udp_timestemp + 1, 0x80,
                            0, ("127.0.0.1", 98765), b"THE_TOKEN"))
        signed_req = SERVER_PKEY.sign(req) + req
        encrypted_req = DEVICE_PKEY.encrypt(signed_req)
        payload = b"\x01" + encrypted_req
        self.handler.on_message(payload, self.serv_sock.getsockname())

        self.assertEqual(
            self.call_history,
            [("require_camera", 0, ["127.0.0.1", 98765], b"THE_TOKEN")])
