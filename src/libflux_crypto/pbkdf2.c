
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated"
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"

#include <openssl/evp.h>

void generate_wpa_psk(const char *pass, int passlen, const unsigned char *salt,
                      int saltlen, unsigned char digest[64]) {
  unsigned char buf[32];
  PKCS5_PBKDF2_HMAC_SHA1(pass, passlen, salt, saltlen, 4096, 32, buf);

  // TODO: Suck..
  unsigned char buf2[65];
  for(int i=0;i<32;i++) {
    sprintf(buf2 + i * 2, "%02x", buf[i]);
  }
  stpncpy(digest, buf2, 64);
}
#pragma GCC diagnostic pop
