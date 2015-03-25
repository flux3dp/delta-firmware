
from base64 import decodestring
from time import time
import unittest
import os

from memcache import Client

from fluxmonitor.misc import security
from tests import _utils as U


class MiscSecurityTest(unittest.TestCase):
    memcache = Client(["127.0.0.1:11211"])

    def setUp(self):
        U.clean_db()

    def test_encrypt_decrypt_msg(self):
        m = security.encrypt_msg(b"HELLO")
        self.assertEqual(security.decrypt_msg(m), b"HELLO")

    def test_encrypt_msg(self):
        access_id = security.add_trust_publickey(U.PUBLICKEY_1)
        m = security.encrypt_msg(b"FLUXMONITOR", access_id=access_id)
        self.assertEqual(m, U.ENCRYPTED_1)

    def test_pubkey_trust(self):
        self.assertFalse(
            security.is_trusted_publickey(U.PUBLICKEY_1))
        security.add_trust_publickey(U.PUBLICKEY_1)
        self.assertTrue(
            security.is_trusted_publickey(U.PUBLICKEY_1))

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
        self.assertFalse(security.has_password())

        t1 = str(time() - 0.1)
        t2 = str(time() + 0.1)
        self.assertTrue(security.set_password(self.memcache, "HELLO", "", t1))
        self.assertTrue(security.validate_password(self.memcache, "HELLO", t2))
        self.assertFalse(security.validate_password(self.memcache, "HELLO", t2))

        self.assertTrue(security.has_password())

        self.memcache.delete("timestemp-%s" % t1)
        self.memcache.delete("timestemp-%s" % t2)
