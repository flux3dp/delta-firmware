
from fluxmonitor.storage import Storage
from hashlib import sha1
from hmac import HMAC

include "halprofile.pxd"
include "security_encrypt.pyx"

DEF PASSWORD_SYMBOL = "private/password"
DEF PUBKEY_SYMBOL = "pub"


cdef extern from "libflux_identify/flux_identify.h":
    RSA* get_machine_rsakey() except NULL
    int get_machine_uuid(unsigned char* [16]) except -1
    RSA* get_rescue_machine_rsakey() except NULL
    int get_rescue_machine_uuid(unsigned char* [16]) except -1


cdef object storage = Storage("security")


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


cpdef bint is_rsakey(object pem=None, object der=None):
    if not pem and not der:
        return False
    try:
        RSAObject(pem=pem, der=der)
        return True
    except TypeError:
        return False


cpdef bint has_password():
    return storage.exists(PASSWORD_SYMBOL)


cpdef bint validate_password(password):
    if has_password():
        with storage.open(PASSWORD_SYMBOL, "r") as f:
            salt, pwdhash = f.read().split(";")
            inputhash = HMAC(salt, password, sha1).hexdigest()
            return pwdhash == inputhash
    else:
        return True
