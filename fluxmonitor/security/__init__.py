
from .identify import get_uuid, get_serial, get_private_key, get_identify

from .access_control import get_keyobj, get_access_id, is_trusted_remote, \
    add_trusted_keyobj, is_rsakey

from .passwd import has_password, set_password, validate_and_set_password, \
    validate_password, validate_timestemp, hash_password

from .misc import randstr, randbytes

from _security import RSAObject, AESObject


def _prepare_cert():
    from binascii import b2a_base64 as to_base64
    from OpenSSL import crypto
    from fluxmonitor.storage import Storage
    s = Storage("security", "private")

    try:
        key = crypto.load_privatekey(crypto.FILETYPE_PEM, s["sslkey.pem"])
    except crypto.Error:
        pkey = get_private_key()
        s["sslkey.pem"] = pem = pkey.export_pem()
        key = crypto.load_privatekey(crypto.FILETYPE_PEM, pem)

    try:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, s["cert.pem"])
    except crypto.Error:
        key = crypto.load_privatekey(crypto.FILETYPE_PEM, pkey.export_pem())
        cert = crypto.X509()
        subj = cert.get_subject()
        subj.C = subj.ST = subj.L = "XX"
        subj.O = "FLUX3dp"
        subj.CN = (get_uuid() + ":" + get_serial() + ":")

        ext = crypto.X509Extension("nsComment", True,
                                   to_base64(get_identify()))
        cert.add_extensions((ext, ))

        cert.set_serial_number(1000)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(10 * 365 * 24 * 60 * 60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(key)
        cert.sign(key, 'sha1')
        s["cert.pem"] = crypto.dump_certificate(crypto.FILETYPE_PEM, cert)

    return s.get_path("cert.pem"), s.get_path("sslkey.pem")

SSL_CERT, SSL_KEY = _prepare_cert()


__all__ = ["SSL_CERT", "SSL_KEY", "get_uuid", "get_serial", "get_private_key",
           "get_identify", "get_keyobj", "get_access_id", "is_trusted_remote",
           "add_trusted_keyobj", "is_rsakey", "has_password", "set_password",
           "validate_and_set_password", "validate_password",
           "validate_timestemp", "hash_password", "randstr", "randbytes",
           "RSAObject", "AESObject"]
