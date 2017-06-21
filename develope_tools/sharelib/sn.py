
from tempfile import NamedTemporaryFile
from subprocess import Popen, PIPE

from fluxmonitor.security._security import RSAObject


def gen_key():
    k = RSAObject(keylength=4096)
    return k.export_der(), k.export_pubkey_der()


def sign_id(private_key, sn, pub_der, uuid, openssl="openssl"):
    p = Popen([openssl, "dgst", "-sha256", "-sign",
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
