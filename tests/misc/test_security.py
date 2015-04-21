
from io import BytesIO
from time import time
import unittest

from fluxmonitor import security
from fluxmonitor.misc import _security
from tests import _utils as U
from tests._utils.memcache import MemcacheTestClient

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA as CryptoSHA


class MiscSecurityTest(unittest.TestCase):
    def setUp(self):
        U.clean_db()
        self.memcache = MemcacheTestClient()

    def test_is_pubkey(self):
        self.assertFalse(security.is_rsakey(None))
        self.assertFalse(security.is_rsakey(""))
        self.assertFalse(security.is_rsakey(3))
        self.assertFalse(security.is_rsakey({}))
        self.assertTrue(security.is_rsakey(der=U.PUBLICKEY_1))

    def test_pubkey_trust(self):
        keyobj = security.get_keyobj(der=U.PUBLICKEY_1)
        assert keyobj

        access_id = security.get_access_id(keyobj=keyobj)
        self.assertFalse(security.is_trusted_remote(der=U.PUBLICKEY_1))
        self.assertFalse(security.is_trusted_remote(keyobj=keyobj))
        self.assertFalse(security.is_trusted_remote(access_id=access_id))

        security.add_trusted_keyobj(keyobj)

        self.assertTrue(security.is_trusted_remote(der=U.PUBLICKEY_1))
        self.assertTrue(security.is_trusted_remote(keyobj=keyobj))
        self.assertTrue(security.is_trusted_remote(access_id=access_id))

    def test_validate_timestemp(self):
        self.assertFalse(security.validate_timestemp(self.memcache,
                                                     (time() - 40, b"a"*128)))
        self.assertFalse(security.validate_timestemp(self.memcache,
                                                     (time() - 40, b"a"*128)))

        t = str(time())
        self.assertTrue(
            security.validate_timestemp(self.memcache, (t, b"a"*128)))
        self.assertFalse(
            security.validate_timestemp(self.memcache, (t, b"a"*128)))
        self.memcache.erase()

        self.assertTrue(security.validate_timestemp(self.memcache,
                                                    (t, b"b"*128), expire=-1))
        self.assertTrue(security.validate_timestemp(self.memcache,
                                                    (t, b"b"*128)))

    def test_password(self):
        self.assertFalse(security.has_password())

        self.assertTrue(security.set_password(self.memcache, "HELLO", ""))
        self.assertTrue(security.validate_password(self.memcache, "HELLO"))
        self.assertFalse(security.validate_password(self.memcache, "HEIIO"))

        self.assertTrue(security.has_password())


class C_RSAObjectTest(unittest.TestCase):
    def encrypt(self, pem, message):
        key = RSA.importKey(pem)
        chip = PKCS1_OAEP.new(key)
        size = ((key.size() + 1) / 8) - 42
        in_buf = BytesIO(message)
        out_buf = BytesIO()

        buf = in_buf.read(size)
        while buf:
            out_buf.write(chip.encrypt(buf))
            buf = in_buf.read(size)

        return out_buf.getvalue()

    def decrypt(self, pem, message):
        key = RSA.importKey(pem)
        chip = PKCS1_OAEP.new(key)
        size = (key.size() + 1) / 8
        in_buf = BytesIO(message)
        out_buf = BytesIO()

        buf = in_buf.read(size)
        while buf:
            try:
                out_buf.write(chip.decrypt(buf))
            except ValueError:
                raise
            buf = in_buf.read(size)

        return out_buf.getvalue()

    def test_basic_create_import_export(self):
        rsaobj = _security.RSAObject(keylength=1024)
        self.assertTrue(rsaobj.is_private())

        pem = rsaobj.export_pem()
        rsaobj = _security.RSAObject(pem=pem)
        self.assertTrue(rsaobj.is_private())

        self.assertEqual(rsaobj.export_pem(), pem)

        self.assertRaises(RuntimeError, _security.RSAObject, pem="123")

    def test_encrype_decrypt(self):
        rsaobj = _security.RSAObject(keylength=1024)
        pem = rsaobj.export_pem()

        P = "WAWAWASUREMONO\x00\x00"
        for buf in [P, P * 8, P * 8 + "!", P * 64, P * 64 + "!"]:
            c_encrypted = rsaobj.encrypt(buf)
            self.assertEqual(self.decrypt(pem, c_encrypted), buf)

            encrypted = self.encrypt(pem, buf)
            self.assertEqual(rsaobj.decrypt(encrypted), buf)

    def test_sign_verify(self):
        rsaobj = _security.RSAObject(keylength=1024)
        pem = rsaobj.export_pem()

        crypto_obj = PKCS1_v1_5.new(RSA.importKey(pem))

        buf = "WASUREMONO"
        c_sign = rsaobj.sign(buf)

        self.assertTrue(rsaobj.verify(buf, c_sign))
        self.assertTrue(crypto_obj.verify(CryptoSHA.new(buf), c_sign))
        self.assertFalse(rsaobj.verify(buf, ""))
        self.assertFalse(rsaobj.verify(buf, "b"))
        self.assertFalse(rsaobj.verify(buf, "b"*127))
        self.assertFalse(rsaobj.verify(buf, "b"*128))
        self.assertFalse(rsaobj.verify(buf, "b"*129))
