
from time import sleep
import logging
import socket
import re

from fluxmonitor.config import MAINBOARD_ENDPOINT, HEADBOARD_ENDPOINT

logger = logging.getLogger(__name__)


def device_startup():
    _try_clean_head_status()

    for i in range(10):
        mb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        mb.settimeout(0.5)
        try:
            mb.connect(MAINBOARD_ENDPOINT)
            mb.send("G28+\n")
            mb.recv(1024)
            return
        except socket.timeout:
            logger.warn("Mainboard I/O timeout")
        except socket.error:
            logger.warn("Connect to mainboard timeout")
        sleep(0.2)


def _try_clean_head_status():
    class Exec(object):
        def __init__(self, s):
            self.s = s

        def send_headboard(self, msg):
            self.s.send(msg)

    def ready_cb():
        pass

    hb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    hb.settimeout(1.5)
    try:
        hb.connect(HEADBOARD_ENDPOINT)

        hb.send("1 HELLO *115\n")

        buf = hb.recv(1024)
        while "\n" not in buf:
            buf += hb.recv(1024)
        if not buf.startswith("1 OK HELLO"):
            logger.warn("Head return unknown handshake msg: %s" % buf)
            return

        for i in xrange(10):
            hb.send("1 PING *33\n")
            buf = hb.recv(1024)
            while "\n" not in buf:
                buf += hb.recv(1024)

            m = re.search("ER:(?P<ER>[\d]+)", buf)
            if m:
                ercode = int(m.groupdict()["ER"])
                if ercode == 0:
                    return
            else:
                logger.warn("Head return unknown msg: %s" % buf)
                return
            sleep(0.8)

    except socket.timeout:
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.exception("Head I/O timeout")
        else:
            logger.warn("Head I/O timeout")
    except socket.error:
        logger.warn("Connect to head timeout")
