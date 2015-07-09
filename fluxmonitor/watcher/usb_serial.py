
from errno import ENOENT, ENOTSOCK
from time import time
import logging
import socket
import struct

from fluxmonitor.hal.nl80211.config import get_wlan_ssid
from fluxmonitor.misc import network_config_encoder as NCE
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.config import network_config
from fluxmonitor.config import uart_config
from fluxmonitor.storage import CommonMetadata
from fluxmonitor import security
from fluxmonitor import STR_VERSION as VERSION
from .base import WatcherBase

logger = logging.getLogger(__name__)

SERIAL_HEX = security.get_uuid()
MODEL_ID = get_model_id()
COMMON_ERRNO = (ENOENT, ENOTSOCK)

MSG_IDENTIFY = 0x00
MSG_RSAKEY = 0x01
MSG_AUTH = 0x02
MSG_CONFIG_GENERAL = 0x03
MSG_CONFIG_NETWORK = 0x04
MSG_GET_SSID = 0x05
MSG_SET_PASSWORD = 0x06



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

        self._recv_buf = bytearray(4096)
        self._recv_view = memoryview(self._recv_buf)
        self._recv_offset = 0
        self._request_len = None

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
        l = self.sock.recv_into(self._recv_view[self._recv_offset:])
        if l:
            self._recv_offset += l
            self.check_recv_buffer()
        else:
            self.callbacks = None
            self.server.close_usb_serial()

    def check_recv_buffer(self):
        if self._request_len is None and self._recv_offset >= 7:
            # Try to unpack new payload

            # Try to find payload header
            try:
                index = self._recv_buf.index(b'\x97\xae\x02')
                if index > 0:
                    # Header found, buf not at index 0, ignore message from
                    # 0 to index
                    remnant = self._recv_offset - index
                    self._recv_view[:remnant] = \
                        self._recv_view[index:self._recv_offset]
                    self._recv_offset = remnant
                    logger.error("Protocol magic number error, shift buffer")

                    if remnant < 7:
                        return

            except ValueError:
                logger.error("Protocol magic number error, clean buffer")
                self._recv_offset = 0
                return

            # Try to unpack payload
            # TODO: python buffer api bug
            req, length = struct.unpack("<HH", self._recv_view[3:7].tobytes())
            if length + 7 <= self._recv_offset:
                # Payload is recived, dispatch it
                self.dispatch_msg()
            else:
                # Payload is not recived yet, mark self._request_len
                if length > 4089:
                    logger.error("Message too large, ignore")
                    self._recv_offset
                self._request_len = length + 7

        elif self._request_len is not None:
            # Try to unpack a padding payload
            if self._recv_offset >= self._request_len:
                self.dispatch_msg()
                self._request_len = None

    def dispatch_msg(self):
        # TODO: python buffer api bug
        req, length = struct.unpack("<HH", self._recv_view[3:7].tobytes())
        try:
            handler = self.callbacks.get(req)
            if handler:
                logger.debug("Request: %s" % handler.__name__)
                handler(self._recv_view[7:7 + length].tobytes())
            else:
                logger.debug("handler not found %i" % req)
        finally:
            remnant = self._recv_offset - length - 7
            if remnant:
                self._recv_view[:remnant] = \
                    self._recv_view[length + 7:self._recv_offset]
            self._recv_offset = remnant

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
                    VERSION, MODEL_ID, SERIAL_HEX, self.meta.get_nickname(),
                    time(), security.has_password(),)
        self.send_response(MSG_IDENTIFY, True, resp.encode())

    def on_rsakey(self, buf):
        pkey = security.get_private_key()
        pem = pkey.export_pubkey_pem()
        self.send_response(MSG_RSAKEY, True, pem)

    def on_auth(self, buf):
        """
        If auth without password, message will be pem format RSA key.
        If auth with password, message comes with 'PASSWORD' prefix,
        the message will be PASSWORD[your password]\\x00[pem format RSA key]
        """
        if buf.startswith(b"PASSWORD"):
            try:
                pwd, pem = buf[8:].split("\x00", 1)
            except ValueError:
                logger.error("Unpack password in on_auth error")
                pwd, pem = "", buf
        else:
            pwd, pem = "", buf

        keyobj = security.get_keyobj(pem=pem)

        if keyobj:
            if security.is_trusted_remote(keyobj=keyobj):
                self.send_response(MSG_AUTH, True, b"ALREADY_TRUSTED")
            else:
                if security.has_password():
                    if security.validate_password(pwd):
                        security.add_trusted_keyobj(keyobj)
                        self.send_response(MSG_AUTH, True, b"OK")
                    else:
                        self.send_response(MSG_AUTH, False, b"BAD_PASSWORD")
                else:
                    security.add_trusted_keyobj(keyobj)
                    self.send_response(MSG_AUTH, True, b"OK")
        else:
            logger.error("Get bad rsa key: %s" % pem.decode("ascii", "ignore"))
            self.send_response(MSG_AUTH, False, b"BAD_KEY", )

    def on_config_general(self, buf):
        raw_opts = dict([i.split(b"=", 1) for i in buf.split(b"\x00")])
        name = raw_opts.get(b"nickname").decode("utf8", "ignore")
        if name:
            self.meta.set_nickname(name)
        self.send_response(MSG_CONFIG_GENERAL, True, b"OK")

    def on_config_network(self, buf):
        try:
            options = NCE.parse_bytes(buf)
            options["ifname"] = "wlan0"
        except ValueError as e:
            self.send_response(MSG_CONFIG_NETWORK, False, b"BAD_PARAMS syntax")
            return
        except KeyError as e:
            self.send_response(MSG_CONFIG_NETWORK, False,
                               ("BAD_PARAMS %s" % e.args[0]).encode())
            return

        nw_request = ("config_network" + "\x00" + \
                      NCE.to_bytes(options)).encode()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(network_config["unixsocket"])
        sock.send(nw_request)
        sock.close()

        self.send_response(MSG_CONFIG_NETWORK, True, b"OK")

    def on_query_ssid(self, buf):
        try:
            ssid = get_wlan_ssid("wlan0")
            if ssid:
                self.send_response(MSG_GET_SSID, True, ssid.encode())
            else:
                self.send_response(MSG_GET_SSID, False, "NOT_FOUND")
        except Exception:
            logger.exception("Error while getting ssid %s" % "wlan0")
            self.send_response(MSG_GET_SSID, False, "NOT_FOUND")
