
from binascii import a2b_hex as from_hex
import unittest
import struct
import socket

from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.event_base import EventBase
from fluxmonitor import security as S

from tests import _utils as U


PRIVATE_KEY = S.get_private_key()
KEY_LENGTH = PRIVATE_KEY.size()


class LocalControlTest(unittest.TestCase):
    def setUp(self):
        self.keyobj = S.get_keyobj(pem=U.PRIVATEKEY_1)

        keyobj = S.get_keyobj(der=U.PUBLICKEY_1)
        S.add_trusted_keyobj(keyobj=keyobj)

        self.access_id = S.get_access_id(keyobj=keyobj)

    def test_on_handshake_identify(self):
        lc = LocalControl(EventBase(), callback=lambda buf, sock: None)

        lc_sock, client_sock = socket.socketpair()

        lc_io = AsyncIO(lc_sock)
        lc_io.client = "192.168.1.2"
        lc.on_connected(lc_io)

        recvbuf = client_sock.recv(8 + PRIVATE_KEY.size() + 128)
        ver, signature, salt = struct.unpack("<8s%is128s" % PRIVATE_KEY.size(),
                                             recvbuf)
        self.assertTrue(PRIVATE_KEY.verify(salt, signature))

        sendbuf = from_hex(self.access_id) + self.keyobj.sign(salt)
        client_sock.send(sendbuf)
        lc.on_handshake(lc_io)
        client_sock.send(sendbuf)

        

        finalbuf = client_sock.recv(16).rstrip(b"\x00")
        self.assertTrue(finalbuf, b"OK")
