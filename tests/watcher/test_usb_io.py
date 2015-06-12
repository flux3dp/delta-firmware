
from time import time
import unittest
import socket
import struct
import os

from Crypto.PublicKey import RSA

from fluxmonitor.watcher.usb_serial import UsbIO
from fluxmonitor.halprofile import get_model_id, get_platform
from fluxmonitor.config import network_config
from fluxmonitor import security

SERIAL = security.get_serial()
MODEL_ID = get_model_id()
MAGIC_NUMBER = b"\x97\xae\x02"


class UsbIoTest(unittest.TestCase):
    def setUp(self):
        self.sock, sock = socket.socketpair()
        self.usbio = UsbIO(self, sock)

    def tearDown(self):
        self.sock.close()
        self.sock = self.usbio = None

    def recv_response(self):
        buf = self.sock.recv(4096)
        mn, req, l, flag = struct.unpack("<3sHHb", buf[:8])
        return mn, req, l, flag, buf[8:]

    def test_dispatch_msg(self):
        REQ0_PAYLOAD = b'\x97\xae\x02\x00\x00\x00\x00'
        REQ1_PAYLOAD = b'\x97\xae\x02\x01\x00\x00\x00'

        def cb(buf):
            raise RuntimeError(buf)

        self.usbio.callbacks = {0: cb}
        with self.assertRaises(RuntimeError) as cm:
            self.usbio.dispatch_msg(REQ0_PAYLOAD)
        self.assertEqual(cm.exception.args[0], REQ0_PAYLOAD)

        self.usbio.dispatch_msg(REQ1_PAYLOAD)

    def test_on_identify(self):
        self.usbio.on_identify(b"")
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(mn, MAGIC_NUMBER)
        self.assertEqual(req, 0)
        self.assertEqual(flag, 1)
        info = dict([keyvalue.split(b"=", 1)
                    for keyvalue in buf.split(b"\x00")])
        self.assertEqual(info["serial"], SERIAL)
        self.assertEqual(info["model"], MODEL_ID)
        self.assertAlmostEqual(float(info["time"]), time(), places=-1)

    def test_on_rsakey(self):
        self.usbio.on_rsakey(b"")
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(mn, MAGIC_NUMBER)
        self.assertEqual(req, 1)
        self.assertEqual(flag, 1)

        RSA.importKey(buf)

    def test_on_auth(self):
        rsa = RSA.generate(1024)
        self.usbio.on_auth(rsa.exportKey().encode())
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(buf, b"OK")

        self.usbio.on_auth(rsa.exportKey().encode())
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(buf, b"ALREADY_TRUSTED")

        self.assertFalse(security.has_password())
        self.assertTrue(security.set_password(None, "TESTPASS", ""))

        rsa = RSA.generate(1024)
        self.usbio.on_auth(rsa.exportKey().encode())
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(buf, "BAD_PASSWORD")

        self.usbio.on_auth(b"PASSWORD1234\x00" + rsa.exportKey().encode())
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(buf, "BAD_PASSWORD")

        self.usbio.on_auth(b"PASSWORDTESTPASS\x00" + rsa.exportKey().encode())
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(buf, "OK")

    def test_on_config_general(self):
        self.usbio.on_config_general(b"nickname=WOW")
        mn, req, l, flag, buf = self.recv_response()
        self.assertEqual(buf, "OK")

    def test_on_config_network_success(self):
        try:
            os.unlink(network_config["unixsocket"])
        except Exception:
            pass

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(network_config["unixsocket"])

        try:
            self.usbio.on_config_network(
                b"method=dhcp\x00ssid=UNITTEST\x00TRASH=TRASH")
            mn, req, l, flag, buf = self.recv_response()
            self.assertEqual(buf, b"OK")
            conf_buf = sock.recv(4096)
            self.assertIn(b"UNITTEST", conf_buf)

        finally:
            sock.close()

    def test_on_config_network_error(self):
        self.usbio.on_config_network(b"errerr")
        mn, req, l, flag, buf = self.recv_response()

        self.assertEqual(buf, "BAD_PARAMS syntax")

    def test_on_query_ssid_simulate(self):
        self.usbio.on_query_ssid(b"")
        mn, req, l, flag, buf = self.recv_response()
