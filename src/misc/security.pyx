
import os


cdef extern from "openssl_bridge.h":
    ctypedef struct EVP_CIPHER_CTX

    EVP_CIPHER_CTX* create_enc_aes256key(const unsigned char* key,
                                         const unsigned char* iv)
    EVP_CIPHER_CTX* create_dec_aes256key(const unsigned char* key,
                                         const unsigned char* iv)
    void free_aes256key(EVP_CIPHER_CTX* ctx)
    unsigned char* aes256_encrypt(EVP_CIPHER_CTX* ctx,
                                  const unsigned char* input,
                                  int inputlen, int* outputlen)

    unsigned char* aes256_decrypt(EVP_CIPHER_CTX* ctx,
                                  const unsigned char* ciphertext,
                                  int inputlen, int* outputlen)

    ctypedef struct RSA
    void RSA_free(RSA*)

    RSA* create_rsa(int)
    RSA* import_der(const char*, int, int)
    RSA* import_pem(const char*, int, int)
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
        self.enc_aeskey = create_enc_aes256key(key, iv)
        self.dec_aeskey = create_dec_aes256key(key, iv)

    def __del__(self):
        free_aes256key(self.enc_aeskey)
        free_aes256key(self.dec_aeskey)

    cpdef encrypt(self, plaintext):
        cdef int outputlen
        output = aes256_encrypt(self.enc_aeskey, plaintext, len(plaintext),
                                &outputlen)
        return output[:outputlen]

    cpdef decrypt(self, ciphertext):
        cdef int outputlen
        output = aes256_decrypt(self.dec_aeskey, ciphertext, len(ciphertext),
                                &outputlen)
        return output[:outputlen]


cdef class RSAObject:
    cdef RSA* rsakey
    cdef int privatekey

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
            raise RuntimeError("Can not load rsa key.")

    def __del__(self):
        if self.rsakey:
            RSA_free(self.rsakey)

    cpdef is_private(self):
        return self.privatekey == 1

    cpdef size(self):
        return rsakey_size(self.rsakey)

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
