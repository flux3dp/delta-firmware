
from binascii import a2b_hex as from_hex
from select import select
import unittest
import pytest
import socket
import pyev
import ssl

from fluxmonitor.interfaces import tcp_ssl
from fluxmonitor.security import RSAObject, hash_password, _prepare_cert
from fluxmonitor.storage import Storage
from tests.fixtures import Fixtures


class SSLHandler(tcp_ssl.SSLConnectionHandler):
    def on_text(self, msg, handler):
        pass

    def on_close(self, handler):
        pass

    def on_ready(self):
        pass


@pytest.mark.usefixtures("default_db")
class SSLHandlerTest(unittest.TestCase):
    def setUp(self):
        host = socket.socket()
        host.bind(("127.0.0.1", 0))
        host.listen(1)

        self.client_sock = cs = socket.socket()
        cs.setblocking(False)
        cs.connect_ex(host.getsockname())
        self.serverSock, self.clientEndpoint = host.accept()
        host.close()

        self.loop = pyev.Loop()
        _prepare_cert()
        s = Storage("security", "private")
        self.certfile = s.get_path("cert.pem")
        self.keyfile = s.get_path("sslkey.pem")

    def tearDown(self):
        self.loop = None

    def on_connected(self, handler):
        pass

    def on_disconnected(self, handler):
        pass

    def complete_ssl_handshake(self, handler, client):
        self.assertRaises(ssl.SSLWantReadError, client.do_handshake)
        ready = False

        while not ready:
            while select((handler.sock, ), (), (), 0)[0]:
                handler.on_recv(None, None)

            while select((client, ), (), (), 0)[0]:
                try:
                    client.do_handshake()
                    ready = True
                    break
                except ssl.SSLWantReadError:
                    pass

        while select((handler.sock, ), (), (), 0)[0]:
            handler.on_recv(None, None)

        self.assertEqual(handler.ready, 1)

    def test_basic_handshake(self):
        with open(Fixtures.keys.path("private1.pem"), "rb") as f:
            key = RSAObject(pem=f.read())

        h = SSLHandler(self, self.serverSock, self.clientEndpoint,
                       self.certfile, self.keyfile)

        self.assertEqual(self.client_sock.recv(8), b"FLUX0003")

        c_sock = ssl.SSLSocket(self.client_sock, do_handshake_on_connect=False)

        self.complete_ssl_handshake(h, c_sock)
        randbytes = c_sock.recv(64)

        # Client send identify
        document = hash_password(tcp_ssl.UUID_BIN, randbytes)
        signature = key.sign(document)
        c_sock.send(from_hex("89ba8bc366d22153e82c22aa6c01f60bcac38c92"))
        c_sock.send(signature)

        # Final identify
        while select((h.sock, ), (), (), 0.05)[0]:
            h.on_recv(None, None)
            if h.ready == 2:
                break

        self.assertEqual(h.ready, 2)

        select((c_sock, ), (), (), 0.1)
        self.assertEqual(c_sock.recv(16), tcp_ssl.MESSAGE_OK)

        # Close socket
        c_sock.close()
        select((h.sock, ), (), (), 1.0)
        h.on_recv(None, None)
        self.assertEqual(h.ready, -1)

    def test_bad_host(self):
        with open(Fixtures.keys.path("private1.pem"), "rb") as f:
            key = RSAObject(pem=f.read())

        h = SSLHandler(self, self.serverSock, self.clientEndpoint,
                       self.certfile, self.keyfile)

        self.assertEqual(self.client_sock.recv(8), b"FLUX0003")

        c_sock = ssl.SSLSocket(self.client_sock, do_handshake_on_connect=False)

        self.complete_ssl_handshake(h, c_sock)
        randbytes = c_sock.recv(64)

        # Client send identify
        document = hash_password(tcp_ssl.UUID_BIN, randbytes)
        signature = key.sign(document)
        c_sock.send(from_hex("89ba8bc366d22153e82c22aa6c01f60bcac38c93"))
        c_sock.send(signature)

        # Final identify
        while select((h.sock, ), (), (), 0.05)[0]:
            h.on_recv(None, None)
            if h.ready == -1:
                break

        self.assertEqual(h.ready, -1)

        select((c_sock, ), (), (), 0.1)
        self.assertEqual(c_sock.recv(16), tcp_ssl.MESSAGE_UNKNOWN_HOST)
