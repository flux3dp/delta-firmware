
from hashlib import sha1
from hmac import HMAC

include "halprofile.pxd"
include "security_encrypt.pyx"


cdef extern from "libflux_identify/flux_identify.h":
    RSA* get_machine_rsakey() except NULL
    int get_machine_uuid(unsigned char* [16]) except -1
    int get_machine_sn(unsigned char* [10]) except -1
    int get_machine_identify(unsigned char**)
    RSA* get_rescue_machine_rsakey() except NULL
    int get_rescue_machine_uuid(unsigned char* [16]) except -1
    int get_rescue_machine_sn(unsigned char* [16]) except -1
    void generate_wpa_psk(const unsigned char*, int, const unsigned char*,
                          int, unsigned char [64])


def get_rsakey(rescue=False):
    cdef RSA* key

    if rescue:
        key = get_rescue_machine_rsakey()
    else:
        key = get_machine_rsakey()

    cdef RSAObject keyobj = RSAObject()
    keyobj.rsakey = key
    return keyobj


def get_uuid(rescue=False):
    cdef unsigned char[16] buf

    if rescue:
        get_rescue_machine_uuid(<unsigned char**>&buf)
    else:
        get_machine_uuid(<unsigned char**>&buf)

    return buf[:16]


def get_serial_number(rescue=False):
    cdef unsigned char[10] buf

    if rescue:
        get_rescue_machine_sn(<unsigned char**>&buf)
    else:
        get_machine_sn(<unsigned char**>&buf)

    return buf[:10]


def get_identify():
    cdef unsigned char* buf
    cdef int length

    length = get_machine_identify(&buf)
    if length == 0:
        raise IOError("NOT_AVAILABLE")
    else:
        return buf[:length]


cpdef bint is_rsakey(object pem=None, object der=None):
    if not pem and not der:
        return False
    try:
        RSAObject(pem=pem, der=der)
        return True
    except TypeError:
        return False


def get_wpa_psk(ssid, passphrase):
  cdef unsigned char[64] buf
  generate_wpa_psk(passphrase, len(passphrase), ssid, len(ssid),
                   <unsigned char*>buf)
  return buf[:64]
