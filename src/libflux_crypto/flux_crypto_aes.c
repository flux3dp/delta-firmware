
#include <Python.h>

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated"
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"

#include <openssl/evp.h>
#include <openssl/aes.h>
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

#pragma GCC diagnostic pop
