
from libc.string cimport strcmp

cdef extern from "libflux_identify/flux_identify.h":
    RSA* get_machine_rsakey() except NULL
    RSA* get_rescue_machine_rsakey() except NULL
    int get_machine_identify(unsigned char**)

    int get_machine_uuid(unsigned char* [16]) except -1
    int get_machine_sn(unsigned char* [10]) except -1
    int get_rescue_machine_uuid(unsigned char* [16]) except -1
    int get_rescue_machine_sn(unsigned char* [16]) except -1
    const char* get_machine_model()


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

    # Attention: return local char* is find because cpython will copy it into
    # python object
    return buf[:10]


def get_model_id(rescue=False):
    cdef unsigned char[10] snbuf
    if strcmp("delta-1", FLUX_MODEL_ID) == 0:
        if get_machine_model()[0] == 0 and get_machine_model()[1] == 1:
            return "delta-1p"
        else:
            get_machine_sn(<unsigned char**>&snbuf);
            delta2018 = snbuf[0] == "F" and snbuf[1] == "D" and snbuf[2] == "1" and snbuf[1] == "P"
            if snbuf[0] == 0 or snbuf[0] == 0xff or delta2018:
                return "delta-1p"
            else:
                return FLUX_MODEL_ID
    else:
        return FLUX_MODEL_ID


def get_rsakey(rescue=False):
    cdef RSA* key

    if rescue:
        key = get_rescue_machine_rsakey()
    else:
        key = get_machine_rsakey()

    cdef RSAObject keyobj = RSAObject()
    keyobj.rsakey = key
    return keyobj


def get_identify():
    cdef unsigned char* buf
    cdef int length

    length = get_machine_identify(&buf)
    if length == 0:
        raise IOError("NOT_AVAILABLE")
    else:
        return buf[:length]


def get_platform():
    return FLUX_PLATFORM


def is_dev_model():
    return FLUX_DEV_MODEL == 1
