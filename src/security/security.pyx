
include "halprofile.pxd"
include "security_encrypt.pyx"
include "security_identify.pyx"


cdef extern from "libflux_crypto/flux_crypto.h":
    void generate_wpa_psk(const unsigned char*, int, const unsigned char*,
                          int, unsigned char [64])


def get_wpa_psk(ssid, passphrase):
  cdef unsigned char[64] buf
  generate_wpa_psk(passphrase, len(passphrase), ssid, len(ssid),
                   <unsigned char*>buf)
  return buf[:64]


cpdef bint is_rsakey(object pem=None, object der=None):
    if not pem and not der:
        return False
    try:
        RSAObject(pem=pem, der=der)
        return True
    except TypeError:
        return False
