
from unittest import TestCase
from math import isnan
import socket


class NanShadow(object):
    def __eq__(self, obj):
        return isnan


class SharedTestCase(TestCase):
    callback_log = None

    def setUp(self):
        self.callback_log = []
        self.lsock, self.rsock = socket.socketpair()
        self.lsock.setblocking(False)
        self.rsock.setblocking(False)

    def assertRecv(self, msg):  # noqa
        buf = self.lsock.recv(4096).decode("ascii")
        self.assertEqual(buf, msg)

    def send_and_process(self, buf):
        self.lsock.send(buf)
        self.t.handle_recv()


nan = NanShadow()
