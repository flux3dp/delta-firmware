
from pkg_resources import resource_string
from errno import ENOENT, ENOTSOCK
from select import select
from time import time
import logging
import socket
import struct
import json

import pyev

from fluxmonitor.hal.nl80211.config import get_wlan_ssid
from fluxmonitor.hal.nl80211.scan import scan as wifiscan
from fluxmonitor.hal.net.monitor import Monitor as NetworkMonitor
from fluxmonitor.misc import network_config_encoder as NCE  # noqa
from fluxmonitor.security.passwd import set_password
from fluxmonitor.security.access_control import is_rsakey, get_keyobj, \
    add_trusted_keyobj, untrust_all
from fluxmonitor.storage import Storage, Metadata
from fluxmonitor.security.misc import randstr
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT, uart_config
from fluxmonitor.err_codes import UNKNOWN_ERROR
from fluxmonitor import security
from fluxmonitor import __version__ as VERSION  # noqa
from .base import ServiceBase

logger = logging.getLogger(__name__)

UUID_HEX = security.get_uuid()
SERIAL = security.get_serial()
MODEL_ID = get_model_id()
COMMON_ERRNO = (ENOENT, ENOTSOCK)

MSG_OK = b"OK"
MSG_CONTINUE = b"continue"

REQ_IDENTIFY = 0x00
REQ_RSAKEY = 0x01
REQ_AUTH = 0x02
REQ_CONFIG_GENERAL = 0x03
REQ_CONFIG_NETWORK = 0x04
REQ_GET_SSID = 0x05
REQ_LIST_SSID = 0x08
REQ_GET_IPADDR = 0x07
REQ_SET_PASSWORD = 0x06

REQ_MAINBOARD_TUNNEL = 0x80
REQ_PHOTO = 0x81
REQ_STORE_DATA = 0x82
REQ_ENABLE_CONSOLE = 0x83


class UsbService(ServiceBase):
    usb = None
    usb_watcher = None

    def __init__(self, options):
        super(UsbService, self).__init__(logger)
        self.timer_watcher = self.loop.timer(0, 30, self.on_timer)
        self.timer_watcher.start()

    def connect_usb_serial(self):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(uart_config["pc"])
            usb = UsbIO(s)
            self.usb = usb
            self.usb_watcher = self.loop.io(usb, pyev.EV_READ,
                                            usb.on_message, self)
            self.usb_watcher.start()
            logger.info("Ready on port %s" % uart_config["pc"])

        except socket.error as e:
            self.close_usb_serial()

            if e.args[0] in COMMON_ERRNO:
                logger.debug("%s" % e)
            else:
                logger.exception("USB Connection error")

    def close_usb_serial(self, *args):
        if self.usb_watcher:
            self.usb_watcher.stop()
            self.usb_watcher = None

        if self.usb:
            self.usb.close()
            self.usb = None

    def on_start(self):
        pass

    def on_shutdown(self):
        pass

    def on_timer(self, watcher, revent):
        if not self.usb:
            self.connect_usb_serial()


class UsbIO(object):
    _vector = None

    def __init__(self, sock):
        self.sock = sock

        self.nw_monitor = NetworkMonitor(None)
        self.meta = Metadata()

        self._recv_buf = bytearray(4096)
        self._recv_view = memoryview(self._recv_buf)
        self._recv_offset = 0
        self._request_len = None

        self.callbacks = {
            REQ_IDENTIFY: self.on_identify,
            REQ_RSAKEY: self.on_rsakey,
            REQ_AUTH: self.on_auth,
            REQ_CONFIG_GENERAL: self.on_config_general,
            REQ_CONFIG_NETWORK: self.on_config_network,
            REQ_GET_SSID: self.on_query_ssid,
            REQ_LIST_SSID: self.on_list_ssid,
            REQ_GET_IPADDR: self.on_query_ipaddr,
            REQ_SET_PASSWORD: self.on_set_password,

            REQ_MAINBOARD_TUNNEL: self.on_mainboard_tunnel,
            REQ_PHOTO: self.on_take_pic,
            REQ_STORE_DATA: self.on_store_data,
            REQ_ENABLE_CONSOLE: self.on_enable_console,
        }

    def fileno(self):
        return self.sock.fileno()

    def on_message(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._recv_view[self._recv_offset:])
            if l:
                self._recv_offset += l
                self.check_recv_buffer()
            else:
                self.callbacks = None
                watcher.data.close_usb_serial()
        except Exception:
            logger.exception("Unhandle error")

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
                    logger.debug("Protocol magic number error, shift buffer")

                    if remnant < 7:
                        return

            except ValueError:
                logger.debug("Protocol magic number error, clean buffer")
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

    def has_request(self):
        return len(select((self.sock, ), (), (), 0)[0]) > 0

    def send_response(self, req, is_success, buf):
        """
            3s: MN
            H: request number
            H: response length
            b: request success=1, error=0
        """
        if self.has_request():
            # Drop this response because already has next request
            logger.warn("Drop req %i because already got next req", req)
            return

        success_flag = 1 if is_success else 0
        header = struct.pack("<3sHHb", b'\x97\xae\x02', req, len(buf),
                             success_flag)
        self.sock.send(header + buf)

    def on_identify(self, buf):
        self._vector = randstr(8)
        resp = ("ver=%s\x00model=%s\x00uuid=%s\x00serial=%s\x00name=%s\x00"
                "time=%.2f\x00pwd=%i\x00vector=%s") % (
                    VERSION, MODEL_ID, UUID_HEX, SERIAL, self.meta.nickname,
                    time(), security.has_password(), self._vector)
        # NOTE: encoding
        self.send_response(REQ_IDENTIFY, True, resp)

    def on_rsakey(self, buf):
        pkey = security.get_private_key()
        pem = pkey.export_pubkey_pem()
        self.send_response(REQ_RSAKEY, True, pem)

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
                self.send_response(REQ_AUTH, True, b"ALREADY_TRUSTED")
            else:
                if security.has_password():
                    if security.validate_password(pwd):
                        security.add_trusted_keyobj(keyobj)
                        self.send_response(REQ_AUTH, True, MSG_OK)
                    else:
                        self.send_response(REQ_AUTH, False, b"BAD_PASSWORD")
                else:
                    security.add_trusted_keyobj(keyobj)
                    self.send_response(REQ_AUTH, True, MSG_OK)
        else:
            logger.error("Get bad rsa key: %s" % pem.decode("ascii", "ignore"))
            self.send_response(REQ_AUTH, False, b"BAD_KEY", )

    def on_config_general(self, buf):
        raw_opts = dict([i.split(b"=", 1) for i in buf.split(b"\x00")])
        name = raw_opts.get(b"name", "").decode("utf8", "ignore")
        if name:
            self.meta.nickname = name.encode("utf8", "ignore")
        self.send_response(REQ_CONFIG_GENERAL, True, MSG_OK)

    def on_config_network(self, buf):
        try:
            options = NCE.parse_bytes(buf)
            options["ifname"] = "wlan0"
        except ValueError as e:
            self.send_response(REQ_CONFIG_NETWORK, False, b"BAD_PARAMS syntax")
            return
        except KeyError as e:
            self.send_response(REQ_CONFIG_NETWORK, False,
                               ("BAD_PARAMS %s" % e.args[0]).encode())
            return

        nw_request = ("config_network" + "\x00" +
                      NCE.to_bytes(options)).encode()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(NETWORK_MANAGE_ENDPOINT)
        sock.send(nw_request)
        sock.close()

        self.send_response(REQ_CONFIG_NETWORK, True, MSG_OK)

    def on_query_ssid(self, buf):
        try:
            ssid = get_wlan_ssid("wlan0")
            self.send_response(REQ_GET_SSID, True, ssid.encode())
        except Exception:
            logger.exception("Error while getting ssid %s" % "wlan0")
            self.send_response(REQ_GET_SSID, False, UNKNOWN_ERROR)

    def on_list_ssid(self, buf):
        try:
            result = wifiscan()
            self.send_response(REQ_LIST_SSID, True, json.dumps(result))
        except Exception:
            logger.exception("Error while list ssid %s" % "wlan0")
            self.send_response(REQ_LIST_SSID, False, UNKNOWN_ERROR)

    def on_query_ipaddr(self, buf):
        status = self.nw_monitor.full_status()
        ipaddrs = []
        for key, data in status.items():
            for ipaddr, mask in data.get("ipaddr", []):
                ipaddrs.append(ipaddr)
        self.send_response(REQ_GET_IPADDR, True, " ".join(ipaddrs))

    def on_set_password(self, buf):
        pwd, pem = buf.split(b"\x00")
        if is_rsakey(pem=pem):
            pubkey = get_keyobj(pem=pem)
            set_password(pwd)
            untrust_all()
            add_trusted_keyobj(pubkey)
            self.send_response(REQ_SET_PASSWORD, True, MSG_OK)
        else:
            self.send_response(REQ_SET_PASSWORD, False, "bad pubkey")

    def on_mainboard_tunnel(self, buf):
        pem = resource_string("fluxmonitor", "data/develope.pem")
        rsakey = get_keyobj(pem=pem)

        salt, signature = buf.split(b"$", 1)

        if rsakey.verify(salt + self._vector, signature):
            from fluxmonitor.diagnosis.usb2device import usb2mainboard

            self.send_response(REQ_MAINBOARD_TUNNEL, True, MSG_CONTINUE)
            usb2mainboard(self.sock, uart_config["mainboard"])
            self.send_response(REQ_MAINBOARD_TUNNEL, True, MSG_OK)

        else:
            self.send_response(REQ_MAINBOARD_TUNNEL, False, "Signature Error")

    def on_take_pic(self, buf):
        pem = resource_string("fluxmonitor", "data/develope.pem")
        rsakey = get_keyobj(pem=pem)

        salt, signature = buf.split(b"$", 1)

        if rsakey.verify(salt + self._vector, signature):
            self.send_response(REQ_PHOTO, True, MSG_CONTINUE)

            from fluxmonitor.diagnosis.usb2device import usb2camera
            usb2camera(self.sock)

            self.send_response(REQ_PHOTO, True, MSG_OK)
        else:
            self.send_response(REQ_PHOTO, False, "Signature Error")

    def on_store_data(self, buf):
        pem = resource_string("fluxmonitor", "data/develope.pem")
        rsakey = get_keyobj(pem=pem)
        location, name, value, m = buf.split('\x00', 3)
        salt, signature = m.split(b'$', 1)

        if rsakey.verify(salt + self._vector, signature):
            s = Storage(location)
            with s.open(name, "w") as f:
                f.write(value)

            self.send_response(REQ_STORE_DATA, True, MSG_OK)
        else:
            self.send_response(REQ_STORE_DATA, False, "Signature Error")

    def on_enable_console(self, buf):
        pem = resource_string("fluxmonitor", "data/develope.pem")
        rsakey = get_keyobj(pem=pem)

        salt, signature = buf.split(b"$", 1)

        if rsakey.verify(salt + self._vector, signature):
            from fluxmonitor.diagnosis.usb2device import enable_console
            ret = enable_console()
            if ret == 0:
                self.send_response(REQ_ENABLE_CONSOLE, True, MSG_OK)
            else:
                self.send_response(REQ_ENABLE_CONSOLE, False, str(ret))
        else:
            self.send_response(REQ_ENABLE_CONSOLE, False, "Signature Error")

    def close(self):
        self.sock.close()
