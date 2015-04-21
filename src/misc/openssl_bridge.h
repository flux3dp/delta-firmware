
#include <Python.h>
#include <openssl/rsa.h>

// keylength: what you see what you get
RSA* create_rsa(int keylength);

// der: RSA key in der format
// length: der length
// is_private: when set to 1, load RSA key as private key
// @return: return NULL if key can not be load
RSA* import_der(const char* der, int length, int is_private);
// der: RSA key in pem format
// length: der length
// is_private: when set to 1, load RSA key as private key
// @return: return NULL if key can not be load
RSA* import_pem(const char* pem, int length, int is_private);

// key: RSA key to be exported
// to_pubkey: if set to 1, export public key
// @return: return key in pem format (Python String). empty string if key can
//          can not export.
PyObject* export_pem(RSA* key, int to_pubkey);

// key: get key size
// @return: return key length. If key is 1024bit, it will return 128
int rsakey_size(const RSA* key);

// key: RSA key
// message: message to be encrypt/decrypt
// length: message length
// @return: what you see, what you get. return Python String. Empty string if
//          error occour.
PyObject* encrypt_message(RSA* key, const unsigned char* message, int length);
PyObject* decrypt_message(RSA* key, const unsigned char* message, int length);
PyObject* sign_message(RSA* key, const unsigned char* message, int length);

// @return: 1 if message is ok, others are failed
int verify_message(RSA*, const unsigned char*, int, const unsigned char*, int);