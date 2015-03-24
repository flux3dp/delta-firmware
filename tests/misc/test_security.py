
from base64 import decodestring
from time import time
import unittest
import os

from memcache import Client

from fluxmonitor.misc import security

security.KEYLENGTH = 1024
PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIICWwIBAAKBgQC3QHviw6z3GA+ribscK+OxGPTxFqCYOYFOOOOH+qSLbYSjsGSD
PO9FcCuTHJUW5hZuvx9h+/Q++yoLUprpKYjSnXMM7LKBi24ZhKI6FbBQ1CJGJ52W
zepyZ1Be25xDPqx2ZbcqKtiiqYU7OYoVWp2oRVba0hbTKvjUQGoEzC0cUQIDAQAB
AoGAavba2Vx6Y6jJzMkSTLlZqI/2uZsJlpFKZsxSE5c74J7Go31czjYNPCzjYnV2
mO0o/u/Uc69LvE+DFSTcg2jZEYo3QUgIeI2HBRdzZFFnHdClApoDU5YJxazlDRHe
c0W+GrGzMEWkZ0KRv/dwKc63KgXC4xOBG3wxWlvFVZnZGAECQQDYhR8RWSycFriT
tL8SaDveQxqn/7mWK+JFrDWre5gmm+6J3NVphuMpQuM8Ib++tcmyR/u9brb/qO2E
XEvOYYlBAkEA2KpzAgEV73byqlYGtkXFikHREV8N/n2xDViNvMyKdkRTIFPLBqUj
m8U2BrIBlyJro1BXZvfp3NJJZUJMz+w/EQJAF8ivu/ketFquldMR9hSrFuQqJnAp
07woU9zx3E9sTDluv4gZjUj65Qpq6a0PYgSYDlRn68wgn/7PcG2vChGewQJAL2ot
vPSL3lnDhS9KTL08G6OHoyuQHm9XPbpxWi3Q50zQfDSaK5wcDMy9o/10h6SKtbSx
S+FZFnAWi8hUkvP6YQJAWF1Y9tLByzG7qth7VC8fsEZaVTpIUa+MBf5BLjCi2pfs
oN8qBR+c7UjbsvPbkWWfkxO6WvdWNiJ+HfQCp9NR1w==
-----END RSA PRIVATE KEY-----"""
ENCRYPTED_MSG = decodestring(
    "UuMBhQGXwxvznqaUKoOeq6qpW0AJoc457R3VucSsRP0fMYrVbAQoeNfouLyI"
    "G4NnJvZEv39/h2dw\nzM5VITjGe5DTruJZY/jHyr3KNiLQf5NByp7IIELfcG"
    "ycOTXDoIv8tDhPjC9y4KKmNhlaKB7puTKC\ngsZ1N5XoBSz6kEnwoVY=\n")


class MiscSecurityTest(unittest.TestCase):
    memcache = Client(["127.0.0.1:11211"])

    def setUp(self):
        # Delete private key
        for fn in (security._get_password_filename(),
                   security._get_key_filename(),):
            if os.path.isfile(fn):
                os.unlink(fn)

    def test_encrypt_decrypt_msg(self):
        m = security.encrypt_msg(b"HELLO")
        self.assertEqual(security.decrypt_msg(m), b"HELLO")

    def test_encrypt_msg(self):
        access_id = security.issue_access_id(PRIVATE_KEY)
        m = security.encrypt_msg(b"HELLO", access_id=access_id)
        self.assertEqual(m, ENCRYPTED_MSG)

    def test_validate_timestemp(self):
        self.assertFalse(
            security.validate_timestemp(self.memcache, time() - 40))
        self.assertFalse(
            security.validate_timestemp(self.memcache, time() + 40))

        t = str(time())
        self.assertTrue(
            security.validate_timestemp(self.memcache, t))
        self.assertFalse(
            security.validate_timestemp(self.memcache, t))
        self.memcache.delete("timestemp-%s" % t)

        self.assertTrue(
            security.validate_timestemp(self.memcache, t, expire=-1))
        self.assertTrue(
            security.validate_timestemp(self.memcache, t))
        self.memcache.delete("timestemp-%s" % t)

    def test_password(self):
        # Delete password file
        t1 = str(time() - 0.1)
        t2 = str(time() + 0.1)
        self.assertTrue(security.set_password(self.memcache, "HELLO", "", t1))
        self.assertTrue(security.validate_password(self.memcache, "HELLO", t2))
        self.assertFalse(security.validate_password(self.memcache, "HELLO", t2))

        self.memcache.delete("timestemp-%s" % t1)
        self.memcache.delete("timestemp-%s" % t2)
        