
from errno import ENOENT, ENOTSOCK
from time import time
import logging
import socket
import struct

from fluxmonitor.hal.nl80211.config import get_wlan_ssid
from fluxmonitor.misc import network_config_encoder
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.config import network_config
from fluxmonitor.config import uart_config
from fluxmonitor.storage import CommonMetadata
from fluxmonitor import security
from fluxmonitor import STR_VERSION as VERSION
from .base import WatcherBase

logger = logging.getLogger(__name__)

SERIAL = security.get_serial()
MODEL_ID = get_model_id()
COMMON_ERRNO = (ENOENT, ENOTSOCK)

MSG_IDENTIFY = 0x00
MSG_RSAKEY = 0x01
MSG_AUTH = 0x02
MSG_CONFIG_GENERAL = 0x03
MSG_CONFIG_NETWORK = 0x04
MSG_GET_SSID = 0x05


class UsbWatcher(WatcherBase):
    usb = None
    usb_io = None

    def __init__(self, server):
        super(UsbWatcher, self).__init__(server, logger)

    def start(self):
        self.connect_usb_serial()

    def connect_usb_serial(self):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(uart_config["pc"])
            io = UsbIO(self, s)

            self.usb_io = io
            self.server.add_read_event(io)
            logger.info("Ready on port %s" % uart_config["pc"])

        except socket.error as e:
            self.close_usb_serial()

            if e.args[0] in COMMON_ERRNO:
                logger.debug("%s" % e)
            else:
                logger.exception("USB Connection error")

    def close_usb_serial(self, *args):
        self.server.remove_read_event(self.usb_id)
        self.usb = None
        self.usb_io = None

    def shutdown(self):
        pass

    def each_loop(self):
        if not self.usb_io:
            self.connect_usb_serial()


class UsbIO(object):
    def __init__(self, server, sock):
        self.sock = sock
        self.server = server
        self.meta = CommonMetadata()
        self.callbacks = {
            MSG_IDENTIFY: self.on_identify,
            MSG_RSAKEY: self.on_rsakey,
            MSG_AUTH: self.on_auth,
            MSG_CONFIG_GENERAL: self.on_config_general,
            MSG_CONFIG_NETWORK: self.on_config_network,
            MSG_GET_SSID: self.on_query_ssid
        }

    def fileno(self):
        return self.sock.fileno()

    def on_read(self, sender):
        buf = self.sock.recv(4096)
        if buf:
            self.dispatch_msg(buf)
        else:
            self.callbacks = None
            self.server.close_usb_serial()

    def dispatch_msg(self, buf):
        lbuf = len(buf)
        if lbuf >= 7 and buf.startswith(b'\x97\xae\x02'):
            req, length = struct.unpack("<HH", buf[3:7])

            if length == lbuf - 7:
                handler = self.callbacks.get(req)
                if handler:
                    handler(buf)
                else:
                    logger.debug("handler not found %i" % req)
            else:
                logger.debug("ignore unmatch message")
        else:
            logger.debug("message too short")

    def send_response(self, req, is_success, buf):
        """
            3s: MN
            H: request number
            H: response length
            b: request success=1, error=0
        """
        success_flag = 1 if is_success else 0
        header = struct.pack("<3sHHb", b'\x97\xae\x02', req, len(buf),
                             success_flag)
        self.sock.send(header + buf)

    def on_identify(self, buf):
        resp = ("ver=%s\x00model=%s\x00serial=%s\x00name=%s\x00"
                "time=%.2f\x00pwd=%i") % (
                VERSION, MODEL_ID, SERIAL, self.meta.get_nickname(),
                time(), security.has_password(),)
        logger.debug("on_identify")
        self.send_response(0, True, resp.encode())

    def on_rsakey(self, buf):
        pkey = security.get_private_key()
        pem = pkey.export_pubkey_pem()
        self.send_response(1, True, pem)

    def on_auth(self, buf):
        if buf.startswith(b"PASSWORD"):
            try:
                pwd, pem = buf[8:].split("\x00", 1)
            except ValueError as e:
                logger.error("Unpack password in on_auth error")
                pwd, pem = "", buf
        else:
            pwd, pem = "", buf

        keyobj = security.get_keyobj(pem=pem)

        if keyobj:
            if security.is_trusted_remote(keyobj=keyobj):
                self.send_response(2, True, b"ALREADY_TRUSTED")
            else:
                if security.has_password():
                    if security.validate_password(None, pwd):
                        security.add_trusted_keyobj(keyobj)
                        self.send_response(2, True, b"OK")
                    else:
                        self.send_response(2, False, b"BAD_PASSWORD")
                else:
                    security.add_trusted_keyobj(keyobj)
                    self.send_response(2, True, b"OK")
        else:
            self.send_response(2, False, b"BAD_KEY")

    def on_config_general(self, buf):
        raw_opts = dict([i.split(b"=", 1) for i in buf.split(b"\x00")])
        name = raw_opts.get(b"nickname").decode("utf8", "ignore")
        if name:
            self.meta.set_nickname(name)
        self.send_response(3, True, b"OK")

    def on_config_network(self, buf):
        try:
            options = network_config_encoder.parse_bytes(buf)
            options["ifname"] = "wlan0"
            nw_request = network_config_encoder.to_bytes(options)
        except ValueError as e:
            self.send_response(4, False, b"BAD_PARAMS syntax")
            return
        except KeyError as e:
            self.send_response(4, False,
                               ("BAD_PARAMS %s" % e.args[0]).encode())
            return

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(network_config["unixsocket"])
        sock.send(nw_request)
        sock.close()

        self.send_response(4, True, b"OK")

    def on_query_ssid(self, buf):
        try:
            ssid = get_wlan_ssid("wlan0")
            if ssid:
                self.send_response(5, True, ssid.encode())
            else:
                self.send_response(5, False, "NOT_FOUND")
        except Exception as e:
            logger.exception("Error while getting ssid %s" % "wlan0")
            self.send_response(5, False, "NOT_FOUND")
