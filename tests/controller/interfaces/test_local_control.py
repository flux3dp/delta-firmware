
from binascii import a2b_hex as from_hex
from pkg_resources import resource_string
import unittest
import pytest
import struct
import socket

from fluxmonitor.controller.interfaces.local import LocalConnectionHandler
from fluxmonitor import security

import pyev


@pytest.mark.usefixtures("empty_security")
class LocalControlTest(unittest.TestCase):
    def setUp(self):
        self.loop = pyev.Loop()
        self.keyobj = security.get_keyobj(
            pem=resource_string("fluxmonitor", "data/test/private_1.pem"))

        keyobj = security.get_keyobj(
            der=resource_string("fluxmonitor", "data/test/public_1.pem"))
        security.add_trusted_keyobj(keyobj=keyobj)

        self.access_id = security.get_access_id(keyobj=keyobj)

    def test_on_handshake_identify(self):
        lc_sock, client_sock = socket.socketpair()
        pkey = security.RSAObject(keylength=512)

        lc_io = LocalConnectionHandler(lc_sock, ("192.168.1.2", 12345),
                                       pkey, self.loop)

        recvbuf = client_sock.recv(8 + pkey.size() + 128)
        ver, signature, salt = struct.unpack("<8s%is128s" % pkey.size(),
                                             recvbuf)
        self.assertTrue(pkey.verify(salt, signature))

        sendbuf = from_hex(self.access_id) + self.keyobj.sign(salt)
        client_sock.send(sendbuf)
        lc_io.on_recv(lc_io.recv_watcher, 0)  # None is watcher
        client_sock.send(sendbuf)

        finalbuf = client_sock.recv(16).rstrip(b"\x00")
        self.assertTrue(finalbuf, b"OK")
