
import unittest

from fluxmonitor.misc._security import AESObject

class C_AESObjectTest(unittest.TestCase):
    def test_bytearray_input(self):
        aesobj = AESObject(b"a"*32, b"b"*16)

        plaintext = "a"*128
        buf = bytearray(plaintext)
        ciphertext = aesobj.encrypt(buf)
        new_plaintext = aesobj.decrypt(ciphertext)
        self.assertEqual(plaintext, new_plaintext)

    def test_memoryview_input(self):
        aesobj = AESObject(b"a"*32, b"b"*16)
        plaintext = "a"*128
        buf = memoryview(plaintext)
        ciphertext = aesobj.encrypt(buf)
        new_plaintext = aesobj.decrypt(ciphertext)
        self.assertEqual(plaintext, new_plaintext)

    def test_bytes_input(self):
        aesobj = AESObject(b"a"*32, b"b"*16)

        plaintext = b"a" * 128
        ciphertext = aesobj.encrypt(plaintext)
        new_plaintext = aesobj.decrypt(ciphertext)
        self.assertEqual(plaintext, new_plaintext)

        plaintext = b"a" * 77
        ciphertext = aesobj.encrypt(plaintext)
        new_plaintext = aesobj.decrypt(ciphertext)
        self.assertEqual(plaintext, new_plaintext)

    def test_operate_into_bytearray(self):
        aesobj = AESObject(b"a"*32, b"b"*16)

        plaintext = "a"*128
        enc_buf = bytearray(128)
        dec_buf = bytearray(128)
        aesobj.encrypt_into(plaintext, enc_buf)
        aesobj.decrypt_into(enc_buf, dec_buf)
        self.assertNotEqual(plaintext, enc_buf)
        self.assertEqual(plaintext, dec_buf)

    def test_operate_into_memoryview(self):
        aesobj = AESObject(b"a"*32, b"b"*16)

        plaintext = "b"*70
        enc_buf = bytearray(70)
        dec_buf = bytearray(70)
        aesobj.encrypt_into(plaintext, memoryview(enc_buf))
        aesobj.decrypt_into(enc_buf, memoryview(dec_buf))
        self.assertNotEqual(plaintext, enc_buf)
        self.assertEqual(plaintext, dec_buf)
