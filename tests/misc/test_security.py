
from pkg_resources import resource_string
from io import BytesIO
from time import time
import unittest

from fluxmonitor import security
from fluxmonitor.security import _security
from fluxmonitor.security.passwd import validate_timestemp, reset_timestemp
from tests._utils import clean_db

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA as CryptoSHA  # noqa

PUBLICKEY_1 = resource_string("fluxmonitor", "data/test/public_1.pem")


class MiscSecurityTest(unittest.TestCase):
    def setUp(self):
        clean_db()

    def test_is_pubkey(self):
        self.assertFalse(security.is_rsakey(None))
        self.assertFalse(security.is_rsakey(""))
        self.assertFalse(security.is_rsakey(3))
        self.assertFalse(security.is_rsakey({}))
        self.assertTrue(security.is_rsakey(der=PUBLICKEY_1))

    def test_pubkey_trust(self):
        keyobj = security.get_keyobj(der=PUBLICKEY_1)
        assert keyobj

        access_id = security.get_access_id(keyobj=keyobj)
        self.assertFalse(security.is_trusted_remote(der=PUBLICKEY_1))
        self.assertFalse(security.is_trusted_remote(keyobj=keyobj))
        self.assertFalse(security.is_trusted_remote(access_id=access_id))

        security.add_trusted_keyobj(keyobj)

        self.assertTrue(security.is_trusted_remote(der=PUBLICKEY_1))
        self.assertTrue(security.is_trusted_remote(keyobj=keyobj))
        self.assertTrue(security.is_trusted_remote(access_id=access_id))

    def test_validate_timestemp(self):
        t = time()
        self.assertFalse(validate_timestemp((t - 40, b"a" * 128)))
        self.assertFalse(validate_timestemp((t - 40, b"a" * 128)))

        self.assertTrue(validate_timestemp((t, b"a" * 128)))
        self.assertFalse(validate_timestemp((t, b"a" * 128)))
        reset_timestemp()

        self.assertTrue(validate_timestemp((60, b"c" * 128), now=60))
        self.assertTrue(validate_timestemp((100, b"c" * 128), now=100))

    def test_password(self):
        self.assertFalse(security.has_password())

        security.set_password("HELLO")
        self.assertTrue(security.validate_password("HELLO"))
        self.assertFalse(security.validate_password("HEIIO"))

        self.assertTrue(security.has_password())


class ClibRSAObjectTest(unittest.TestCase):
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

        self.assertRaises(TypeError, _security.RSAObject, pem="123")

    def test_encrype_decrypt(self):
        rsaobj = _security.RSAObject(keylength=1024)
        pem = rsaobj.export_pem()

        p = "WAWAWASUREMONO\x00\x00"
        for buf in [p, p * 8, p * 8 + "!", p * 64, p * 64 + "!"]:
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
        self.assertFalse(rsaobj.verify(buf, "b" * 127))
        self.assertFalse(rsaobj.verify(buf, "b" * 128))
        self.assertFalse(rsaobj.verify(buf, "b" * 129))

    def test_export_der(self):
        rsaobj = _security.RSAObject()
        der_buffer = rsaobj.export_der()

        new_rsaobj = _security.RSAObject(der=der_buffer)
        self.assertEqual(der_buffer, new_rsaobj.export_der())
        self.assertEqual(rsaobj.export_pem(), new_rsaobj.export_pem())

        pub_rsakey = _security.RSAObject(der=rsaobj.export_pubkey_der())
        self.assertEqual(rsaobj.export_pubkey_pem(),
                         pub_rsakey.export_pubkey_pem())


class ClibMiscTest(unittest.TestCase):
    def test_wifi_psa(self):
        psk = _security.get_wpa_psk("aaaaaaaa", "aaaaaaaa")
        self.assertEqual(psk,
                         "d90c1a12c3a2e7a986bdaa9f45158762"
                         "3af652a47489853493e02d861fb8a37e")

        psk = _security.get_wpa_psk("my_wifi", "wifi_password")
        self.assertEqual(psk,
                         "0e7b8afb6abd81824140e398be47a732"
                         "afa2a6d913cff60d8829ac688f4a7eec")
