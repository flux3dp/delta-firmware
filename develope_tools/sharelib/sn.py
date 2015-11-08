
from tempfile import NamedTemporaryFile
from subprocess import Popen, PIPE
from hashlib import sha256
from uuid import UUID
import struct

from fluxmonitor.security._security import RSAObject

CHKSUMBASE = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _get_checksum(digest, length=2):
    s = 0
    size = len(CHKSUMBASE)
    maxsize = size * size
    for c in digest:
        s += ord(c)
        if s >= maxsize:
            s %= maxsize
    chkstr = []
    for i in range(length):
        chkstr.append(CHKSUMBASE[s % size])
        s //= size

    chkstr.reverse()
    return "".join(chkstr)


def gen_key():
    k = RSAObject(keylength=4096)
    return k.export_der(), k.export_pubkey_der()


def sign_id(private_key, sn, pub_der, uuid):
    p = Popen(["openssl", "dgst", "-ecdsa-with-SHA1", "-sign",
              private_key], stdin=PIPE, stdout=PIPE)
    p.stdin.write(sn.encode())
    p.stdin.write(b"$")
    p.stdin.write(uuid.bytes)
    p.stdin.write(b"$")
    p.stdin.write(pub_der)
    p.stdin.close()

    buf = b""
    while p.poll() is None:
        buf += p.stdout.read()
    buf += p.stdout.read()

    if p.returncode > 0:
        raise RuntimeError("Sign failed")

    return buf


def validate_id(public_key, sn, pub_der, uuid, signature):
    f = NamedTemporaryFile()
    f.write(signature)
    f.flush()

    p = Popen(["openssl", "dgst", "-ecdsa-with-SHA1", "-verify",
               public_key, "-signature", f.name], stdin=PIPE, stdout=PIPE)
    p.stdin.write(sn.encode())
    p.stdin.write(b"$")
    p.stdin.write(uuid.bytes)
    p.stdin.write(b"$")
    p.stdin.write(pub_der)
    p.stdin.close()

    buf = b""
    while p.poll() is None:
        buf += p.stdout.read()
    buf += p.stdout.read()

    if p.returncode > 0:
        raise RuntimeError("Sign failed")

    return buf


def get_sn(prefix, index):
    eng = sha256()
    eng.update(b"FLUX")
    eng.update(prefix.encode())

    if index > 25599:
        raise ValueError("index can not exceed 25599")

    index_str = "%(INDEX_B)02X%(INDEX_A)02i" % {
        "INDEX_B": index // 100,
        "INDEX_A": index % 100
    }

    eng.update(index_str.encode())
    chksum = _get_checksum(eng.digest())

    return "%s%s%s" % (prefix, chksum, index_str)


def get_uuid(prefix, index, identify):
    # 4-2-2-2-6
    b = struct.pack(">4sH10s", prefix, index, sha256(identify).digest()[:10])
    return UUID(bytes=b)
