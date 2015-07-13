
from cpython.buffer cimport PyBUF_SIMPLE, PyObject_GetBuffer, PyBuffer_Release
from libc.stdlib cimport malloc, free
import os


cdef extern from "libflux_crypto/flux_crypto.h":
    ctypedef struct EVP_CIPHER_CTX

    EVP_CIPHER_CTX* create_enc_aes256key(const unsigned char* key,
                                         const unsigned char* iv)
    EVP_CIPHER_CTX* create_dec_aes256key(const unsigned char* key,
                                         const unsigned char* iv)
    void free_aes256key(EVP_CIPHER_CTX* ctx)
    int aes256_encrypt(EVP_CIPHER_CTX* ctx, const unsigned char* plaintext,
                       unsigned char* ciphertext, int length)

    int aes256_decrypt(EVP_CIPHER_CTX* ctx, const unsigned char* ciphertext,
                       unsigned char* plaintext, int length)

    ctypedef struct RSA
    void RSA_free(RSA*)

    RSA* create_rsa(int)
    RSA* import_der(const char*, int, int)
    RSA* import_pem(const char*, int, int)
    object export_der(RSA*, int)
    object export_pem(RSA*, int)
    int rsakey_size(const RSA*)
    object encrypt_message(RSA* key, const unsigned char*, int)
    object decrypt_message(RSA*, const unsigned char*, int)
    object sign_message(RSA*, const unsigned char*, int)
    int verify_message(RSA*, const unsigned char*, int, const unsigned char*, int)


cdef class AESObject:
    cdef EVP_CIPHER_CTX* enc_aeskey
    cdef EVP_CIPHER_CTX* dec_aeskey

    def __init__(self, key, iv):
        if len(key) != 32:
            raise Exception("key must be 32 bytes")
        if len(iv) != 16:
            raise Exception("iv must be 16 bytes")
        self.enc_aeskey = create_enc_aes256key(key, iv)
        self.dec_aeskey = create_dec_aes256key(key, iv)

    def __dealloc__(self):
        free_aes256key(self.enc_aeskey)
        free_aes256key(self.dec_aeskey)

    cpdef encrypt(self, plaintext):
        cdef Py_buffer view
        cdef int length = len(plaintext)
        cdef unsigned char* buf= <unsigned char *>malloc(length)
        try:
            PyObject_GetBuffer(plaintext, &view, PyBUF_SIMPLE)
            ret = aes256_decrypt(self.enc_aeskey,
                                 <const unsigned char*>view.buf, buf, length)
            return <bytes>buf[:len(plaintext)]
        finally:
            PyBuffer_Release(&view)
            free(buf)

    cpdef encrypt_into(self, plaintext, unsigned char[:] ciphertext):
        cdef Py_buffer view
        cdef int length = len(plaintext)

        if length > len(ciphertext):
            raise Exception("Output buffer too small (%i, %i)" %
                            (len(plaintext), len(ciphertext)))
        try:
            PyObject_GetBuffer(plaintext, &view, PyBUF_SIMPLE)
            ret = aes256_encrypt(self.enc_aeskey,
                                 <const unsigned char*>view.buf,
                                 &(ciphertext[0]), length)
            return ret
        finally:
            PyBuffer_Release(&view)

    cpdef decrypt(self, ciphertext):
        cdef Py_buffer view
        cdef int length = len(ciphertext)
        cdef unsigned char* buf= <unsigned char *>malloc(length)
        try:
            PyObject_GetBuffer(ciphertext, &view, PyBUF_SIMPLE)
            ret = aes256_decrypt(self.dec_aeskey,
                                 <const unsigned char*>view.buf, buf, length)
            return <bytes>buf[:len(ciphertext)]
        finally:
            PyBuffer_Release(&view)
            free(buf)

    cpdef decrypt_into(self, ciphertext, unsigned char[:] plaintext):
        cdef Py_buffer view
        cdef int length = len(plaintext)

        if len(plaintext) < len(ciphertext):
            raise Exception("Output buffer too small (%i, %i)" %
                            (len(ciphertext), len(plaintext)))
        try:
            PyObject_GetBuffer(ciphertext, &view, PyBUF_SIMPLE)
            ret = aes256_decrypt(self.dec_aeskey,
                                 <const unsigned char*>view.buf,
                                 &(plaintext[0]), length)
            return plaintext
        finally:
            PyBuffer_Release(&view)


cdef class RSAObject:
    cdef RSA* rsakey
    cdef int privatekey

    def __cinit__(self):
        pass

    def __init__(self, pem=None, der=None, keylength=1024):
        self.privatekey = 0
        if der != None:
            self.rsakey = import_der(der, len(der), 1)
            if self.rsakey:
                self.privatekey = 1
            else:
                self.rsakey = import_der(der, len(der), 0)

        elif pem != None:
            self.rsakey = import_pem(pem, len(pem), 1)
            if self.rsakey:
                self.privatekey = 1
            else:
                self.rsakey = import_pem(pem, len(pem), 0)

        else:
            self.rsakey = create_rsa(keylength)
            self.privatekey = 1

        if not self.rsakey:
            raise TypeError("Can not load rsa key.")

    def __dealloc__(self):
        if self.rsakey:
            RSA_free(self.rsakey)

    cpdef is_private(self):
        return self.privatekey == 1

    cpdef size(self):
        return rsakey_size(self.rsakey)

    cpdef export_der(self):
        if self.privatekey == 1:
            return export_der(self.rsakey, 0) # export private key
        else:
            return export_der(self.rsakey, 1) # export public key

    cpdef export_pubkey_der(self):
        return export_der(self.rsakey, 1) # export public key

    cpdef export_pem(self):
        if self.privatekey == 1:
            return export_pem(self.rsakey, 0) # export private key
        else:
            return export_pem(self.rsakey, 1) # export public key

    cpdef export_pubkey_pem(self):
        return export_pem(self.rsakey, 1) # export public key

    cpdef encrypt(self, message):
        return encrypt_message(self.rsakey, message, len(message))

    cpdef decrypt(self, message):
        return decrypt_message(self.rsakey, message, len(message))

    cpdef sign(self, message):
        if self.privatekey == 1:
            return sign_message(self.rsakey, message, len(message))
        else:
            raise RuntimeError("Public Key can not sign")

    cpdef verify(self, message, sig):
        return verify_message(self.rsakey, message, len(message),
                              sig, len(sig)) == 1
