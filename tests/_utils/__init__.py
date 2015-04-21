
from shutil import rmtree
import socket
import os


from fluxmonitor.config import general_config
from fluxmonitor import security


def clean_db(default_privatekey=True):
    for del_dir in (os.path.join(general_config["db"], "security"),
                    os.path.join(general_config["db"], "net")):
        if os.path.isdir(del_dir):
            rmtree(del_dir)

    if default_privatekey:
        with open(security._get_key_filename(), "w") as f:
            f.write("""-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQDGTG+rsxKCy52sjsc8dr4O0WcuZpFWIKNRj8OdUi9KJLuNknaX
bEHQ/MP/AC2fUi01pDgNi9/DNxz+P2d+DdJuMt1staDDgP3ZrfxDWqcXKJi33oXe
Oe293KkH8GqPU4VbTF/YnPl/l8vNcsbc25SvBTq12dBeBl3nWgEXNw4ARwIDAQAB
AoGAM4BUnHZkv12ctN1cN4Lrd7PBJZbz9jeB00QQXQKkT5BcubcpX8h5C4sqaEcm
kjNolH7zI+mJEw10VUAoY9+5H/oPkO0E6HCCXM8IfuzHkppe9wraH/5iijYvNK4x
cXFZNgSWdKG7ZLPgOn2mqm2cZC1+WpZws9BcySc57BuL0pECQQD7W589zLEXnK74
2aSGLGld7rqU6qKn5/U8ZpV+5ZduIhwrmPjTnob0FzW7QQdlxGppLwBYMN1qER7/
vIQGAZTfAkEAyfX1Z/p+KzDtkCG0H3KFdF6d1HC7NZPFCRlMiTiRwskIkKdzqM7R
2L0GUxyccEBZ4NEYkIIvZGqZhGEhoXXZmQJAXlyABHhCh0W33g3+mKw1hiDoBJ2t
IHGQ+/La7n+MgLjncGqGBxO9QAcykbCQ8WByPjh53aHCjV4OEB2aRpLzawJAYKPR
SnAS75f6FX4LMwEZ2xVrcLyA2KJdJn10ojTvisWn05BNR/mvcIcC/8IxGYWxfGKR
3pRtGR/pVe8kqJ48AQJBAMQMFk+MwgS3Ayx0hVBgsmGJHP8g19sanuKlavJZzCAd
gtvsnhncn8pKiFOADK906WpEh/GAyrAEF/V4q4iDFZU=
-----END RSA PRIVATE KEY-----""")


def create_unix_socket(path):
    if os.path.exists(path):
        os.unlink(path)
    us = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    us.bind(path)
    us.setblocking(False)

    return us


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
