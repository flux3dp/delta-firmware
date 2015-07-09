
from fluxmonitor.storage import Storage
from hashlib import sha1
from hmac import HMAC

include "halprofile.pxd"
include "security_encrypt.pyx"

DEF PASSWORD_SYMBOL = "private/password"
DEF PUBKEY_SYMBOL = "pub"

cdef object storage = Storage("security")


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
