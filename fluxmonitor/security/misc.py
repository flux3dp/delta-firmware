
from random import choice

STR_BASE = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def randstr(length=8):
    return "".join((choice(STR_BASE) for i in range(length)))


def randbytes(length=128):
    with open("/dev/urandom") as f:
        return f.read(length)
