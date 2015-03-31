
from shutil import rmtree
import socket
import os

from fluxmonitor.config import general_config


def clean_db():
    for del_dir in (os.path.join(general_config["db"], "security"),
                    os.path.join(general_config["db"], "net")):
        if os.path.isdir(del_dir):
            rmtree(del_dir)


def create_unix_socket(path):
    if os.path.exists(path):
        os.unlink(path)
    us = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    us.bind(path)
    us.setblocking(False)

    return us

LOCAL_HOSTNAME = socket.gethostname()
LOCAL_IPADDR = socket.gethostbyname(LOCAL_HOSTNAME)

with open(os.path.join(os.path.dirname(__file__), "private_1.pem")) as f:
    PRIVATEKEY_1 = f.read()
with open(os.path.join(os.path.dirname(__file__), "private_2.pem")) as f:
    PRIVATEKEY_2 = f.read()
with open(os.path.join(os.path.dirname(__file__), "private_3.pem")) as f:
    PRIVATEKEY_3 = f.read()
with open(os.path.join(os.path.dirname(__file__), "public_1.pem")) as f:
    PUBLICKEY_1 = f.read()
with open(os.path.join(os.path.dirname(__file__), "public_2.pem")) as f:
    PUBLICKEY_2 = f.read()
with open(os.path.join(os.path.dirname(__file__), "public_3.pem")) as f:
    PUBLICKEY_3 = f.read()
with open(os.path.join(os.path.dirname(__file__), "encrypted_1.data")) as f:
    ENCRYPTED_1 = f.read()
with open(os.path.join(os.path.dirname(__file__), "encrypted_2.data")) as f:
    ENCRYPTED_2 = f.read()
with open(os.path.join(os.path.dirname(__file__), "encrypted_3.data")) as f:
    ENCRYPTED_3 = f.read()

KEYPAIR1 = (PRIVATEKEY_1, PUBLICKEY_1)
KEYPAIR2 = (PRIVATEKEY_2, PUBLICKEY_2)
KEYPAIR3 = (PRIVATEKEY_3, PUBLICKEY_3)
