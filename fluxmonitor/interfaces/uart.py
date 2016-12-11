
from select import select
from errno import ENOENT, ENOTSOCK
import logging
import struct
import pyev
import json

from fluxmonitor.security.misc import randstr
from fluxmonitor import security
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.misc import network_config_encoder as NCE  # noqa
from fluxmonitor.err_codes import UNKNOWN_ERROR
from fluxmonitor.hal.misc import get_deviceinfo
from fluxmonitor.storage import metadata
from fluxmonitor.config import UART_ENDPOINT
from .usb_config import ConfigureTools
from .handler import UnixHandler

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

REQ_ENABLE_TTY = 0x83
REQ_ENABLE_SSH = 0x84

logger = logging.getLogger(__name__)


class UartHandler(UnixHandler):
    _vector = None

    def __init__(self, kernel, endpoint=UART_ENDPOINT,
                 on_connected_callback=None, on_close_callback=None):
        super(UartHandler, self).__init__(
            kernel, endpoint,
            on_connected_callback=on_connected_callback,
            on_close_callback=on_close_callback)

    def on_connected(self):
        super(UnixHandler, self).__init__()
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

            REQ_ENABLE_TTY: self.on__enable_tty,
            REQ_ENABLE_SSH: self.on__enable_ssh
        }
        self.watcher.stop()
        self.watcher.callback = self.on_message
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.start()

    def on_message(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._recv_view[self._recv_offset:])
            if l:
                self._recv_offset += l
                self.check_recv_buffer()
            else:
                self.on_error()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

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
        except RuntimeError as e:
            logger.info("Uart request error: %s", e)
            self.send_response(req, False, " ".join(e.args).encode(), )
        except Exception:
            logger.exception("Command execute failed")
            self.send_response(req, False, "UNKNOWN_ERROR")
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
        info = {"time": time(), "pwd": 1 if security.has_password() else 0,
                "vector": self._vector}
        info.update(get_deviceinfo(metadata))
        info["ver"] = info.pop("version")
        info["name"] = info.pop("nickname")
        resp = "\x00".join(("%s=%s" % kv for kv in info.items()))
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
        ConfigureTools.request_set_nickname(name.encode("utf8", "ignore"))
        self.send_response(REQ_CONFIG_GENERAL, True, MSG_OK)

    def on_config_network(self, buf):
        try:
            options = NCE.parse_bytes(buf)
            if "ifname" not in options:
                options["ifname"] = "wlan0"

            request_data = NCE.build_network_config_request(options)
            NCE.send_network_config_request(request_data)
            self.send_response(REQ_CONFIG_NETWORK, True, MSG_OK)

        except ValueError as e:
            self.send_response(REQ_CONFIG_NETWORK, False, b"BAD_PARAMS syntax")
            return
        except KeyError as e:
            self.send_response(REQ_CONFIG_NETWORK, False,
                               ("BAD_PARAMS %s" % e.args[0]).encode())
            return

    def on_query_ssid(self, buf):
        try:
            ssid = ConfigureTools.request_get_wifi("wlan0")["ssid"]
            self.send_response(REQ_GET_SSID, True, ssid.encode())
        except Exception:
            logger.exception("Error while getting ssid %s" % "wlan0")
            self.send_response(REQ_GET_SSID, False, UNKNOWN_ERROR)

    def on_list_ssid(self, buf):
        try:
            result = ConfigureTools.request_scan_wifi()
            self.send_response(REQ_LIST_SSID, True, json.dumps(result))
        except RuntimeError as e:
            logger.exception("Error while list ssid %s" % "wlan0")
            self.send_response(REQ_LIST_SSID, False, e.args[0])
        except Exception:
            logger.exception("Error while list ssid %s" % "wlan0")
            self.send_response(REQ_LIST_SSID, False, UNKNOWN_ERROR)

    def on_query_ipaddr(self, buf):
        ipaddrs = ConfigureTools.request_get_ipaddr("wlan0")["ipaddrs"]
        ipaddrs += ConfigureTools.request_get_ipaddr("eth0")["ipaddrs"]
        self.send_response(REQ_GET_IPADDR, True, " ".join(ipaddrs))

    def on_set_password(self, buf):
        pwd, pem = buf.split(b"\x00")
        try:
            ConfigureTools.uart_set_password(pwd, pem)
            self.send_response(REQ_SET_PASSWORD, True, MSG_OK)
        except RuntimeError:
            self.send_response(REQ_SET_PASSWORD, False, "bad pubkey")

    def on__enable_tty(self, buf):
        salt, signature = buf.split(b"$", 1)
        ConfigureTools.request__enable_tty(salt + self._vector, signature)
        self.send_response(REQ_ENABLE_TTY, True, MSG_OK)

    def on__enable_ssh(self, buf):
        salt, signature = buf.split(b"$", 1)
        ConfigureTools.request__enable_tty(salt + self._vector, signature)
        self.send_response(REQ_ENABLE_TTY, True, MSG_OK)
