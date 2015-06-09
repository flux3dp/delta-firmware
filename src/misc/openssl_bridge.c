
#include <Python.h>

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated"
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"

#include <openssl/evp.h>
#include <openssl/aes.h>
#include <openssl/rsa.h>
#include <openssl/pem.h>
#include <openssl/sha.h>
#include <openssl/x509.h>
#include <openssl/err.h>
#include <openssl/objects.h>


EVP_CIPHER_CTX* create_enc_aes256key(const unsigned char* key,
                                     const unsigned char* iv) {
    EVP_CIPHER_CTX* ctx = malloc(sizeof(EVP_CIPHER_CTX));
    EVP_CIPHER_CTX_init(ctx);
    EVP_EncryptInit(ctx, EVP_aes_256_cfb8(), key, iv);
    return ctx;
}

EVP_CIPHER_CTX* create_dec_aes256key(const unsigned char* key,
                                     const unsigned char* iv) {
    EVP_CIPHER_CTX* ctx = malloc(sizeof(EVP_CIPHER_CTX));
    EVP_CIPHER_CTX_init(ctx);
    EVP_DecryptInit(ctx, EVP_aes_256_cfb8(), key, iv);
    return ctx;
}

void free_aes256key(EVP_CIPHER_CTX* ctx) {
    EVP_CIPHER_CTX_cleanup(ctx);
    free(ctx);
}

int aes256_encrypt(EVP_CIPHER_CTX* ctx, const unsigned char* plaintext,
                   unsigned char* ciphertext, int length) {
    int ol = length;
    int ret = EVP_EncryptUpdate(ctx, ciphertext, &ol, plaintext, length);
    return ret;
}

int aes256_decrypt(EVP_CIPHER_CTX* ctx,
                              const unsigned char* ciphertext,
                              unsigned char* plaintext, int length) {
    int ol = length;
    int ret = EVP_DecryptUpdate(ctx, plaintext, &ol, ciphertext, length);
    return ret;
}

RSA* create_rsa(int keylen) {
    RSA *rsa = NULL;
    BIGNUM *bne = NULL;
    int ret = 0;

    bne = BN_new();
    ret = BN_set_word(bne, RSA_F4);
    if(ret != 1) {
        BN_free(bne);
        return NULL;
    }

    rsa = RSA_new();
    ret = RSA_generate_key_ex(rsa, keylen, bne, NULL);
    if(ret != 1) {
        BN_free(bne);
        RSA_free(rsa);
        return NULL;
    }

    return rsa;
}

RSA* import_der(void* der, int length, int is_private) {
    BIO *bio = BIO_new_mem_buf(der, length);
    RSA *rsa = NULL;
    if(is_private) {
        d2i_RSAPrivateKey_bio(bio, &rsa);
    } else {
        d2i_RSA_PUBKEY_bio(bio, &rsa);
    }
    BIO_free(bio);
    return rsa;
}

RSA* import_pem(void* pem, int length, int is_private) {
    BIO *bio = BIO_new_mem_buf(pem, length);
    RSA *rsa = NULL;
    if(is_private) {
        PEM_read_bio_RSAPrivateKey(bio, &rsa, 0, NULL);
    } else {
        PEM_read_bio_RSA_PUBKEY(bio, &rsa, 0, NULL);
    }
    BIO_free(bio);
    return rsa;
}

PyObject* export_pem(RSA* key, int to_pubkey) {
    BIO *bio = BIO_new(BIO_s_mem());

    if(to_pubkey) {
        PEM_write_bio_RSA_PUBKEY(bio, key);
    } else {
        PEM_write_bio_RSAPrivateKey(bio, key, NULL, NULL, 0, NULL, NULL);
    }

    int pemlen = BIO_pending(bio);
    void* pem = calloc(pemlen + 1, 1); /* Null-terminate */
    BIO_read(bio, pem, pemlen);
    PyObject* result = Py_BuildValue("s", pem);

    BIO_free(bio);
    free(pem);

    return result;
}

int rsakey_size(const RSA* key) {
    return RSA_size(key);
}

PyObject* encrypt_message(RSA* key, const unsigned char *message, int length) {
    int keysize = RSA_size(key);

    int chunk_size = keysize - 42;
    int outputlen = (length / chunk_size) * keysize;
    if((length % chunk_size) > 0) outputlen += keysize;

    unsigned char *encbuf = malloc(outputlen);
    const unsigned char *message_ptr = message;
    unsigned char *encbuf_ptr = encbuf;

    for(int i=0;i<length;i+=chunk_size) {
        int l = length - i;
        if(l > chunk_size) l = chunk_size;
        RSA_public_encrypt(l, message_ptr, encbuf_ptr, key, RSA_PKCS1_OAEP_PADDING);
        encbuf_ptr += keysize;
        message_ptr += chunk_size;
    }

    PyObject* result = Py_BuildValue("s#", encbuf, outputlen);
    free(encbuf);
    return result;
}

PyObject* decrypt_message(RSA* key, const unsigned char* message, int length) {
    int keysize = RSA_size(key);
    int sections = length / keysize;

    if(length % keysize != 0)
        return Py_BuildValue("s", "");

    // Maximum memory wll be use
    // int reallength = 0;
    unsigned char *decbuf = malloc((keysize - 42) * sections);
    unsigned char *decbuf_ptr = decbuf;

    for(int i=0;i<sections;i++) {
        int l = RSA_private_decrypt(keysize, message, decbuf_ptr, key, RSA_PKCS1_OAEP_PADDING);
        decbuf_ptr += l;
        message += keysize;
    }

    PyObject* result = Py_BuildValue("s#", decbuf, decbuf_ptr - decbuf);
    free(decbuf);
    return result;
}

PyObject* sign_message(RSA* key, const unsigned char* message, int length) {
    unsigned int keysize = RSA_size(key);
    unsigned char *sigret = malloc(keysize);

    unsigned char hash[20];
    SHA1(message, length, (unsigned char (*) [20])(&hash));
    int ret = RSA_sign(NID_sha1, hash, 20, sigret, &keysize, key);
    PyObject* result;

    if(ret == 1) {
        result = Py_BuildValue("s#", sigret, keysize);
    } else {
        result = Py_BuildValue("s", "");
    }

    free(sigret);
    return result;
}

int verify_message(RSA *key, const unsigned char* message, int length,
                   unsigned char *sigbuf, int siglen) {
    unsigned char hash[20];
    SHA1(message, length, (unsigned char (*) [20])(&hash));
    int ret = RSA_verify(NID_sha1, hash, 20, sigbuf, siglen, key);

    return ret;
}
#pragma GCC diagnostic pop

