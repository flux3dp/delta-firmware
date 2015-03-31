
from time import time, sleep
from itertools import chain
import uuid as _uuid
import binascii
import logging
import struct
import socket
import json

logger = logging.getLogger(__name__)

from fluxmonitor.config import network_config
from fluxmonitor.misc import security
from fluxmonitor import VERSION as _VERSION
from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix

VERSION = ".".join((str(i) for i in _VERSION))
MODEL = "flux3dp:1"
DEFAULT_PORT = 3310


CODE_DISCOVER = 0x00
CODE_RESPONSE_DISCOVER = 0x01

CODE_RSA_KEY = 0x02
CODE_RESPONSE_RSA_KEY = 0x03

CODE_NOPWD_ACCESS = 0x04
CODE_RESPONSE_NOPWD_ACCESS = 0x05

CODE_PWD_ACCESS = 0x06
CODE_RESPONSE_PWD_ACCESS = 0x07

CODE_CHANGE_PWD = 0x08
CODE_RESPONSE_CHANGE_PWD = 0x09

CODE_SET_NETWORK = 0x0a
CODE_RESPONSE_SET_NETWORK = 0x0b

GLOBAL_SERIAL = _uuid.UUID(int=0)


class UpnpServicesMix(object):
    padding_request_pubkey = None

    def cmd_discover(self, payload):
        """Return IP Address in array"""
        # TODO: NOT CONFIRM
        return {"code": CODE_RESPONSE_DISCOVER, "ver": VERSION,
                "model": MODEL, "serial": security.get_serial(),
                "time": time(), "ip": self.ipaddress,
                "pwd": security.has_password()}

    def cmd_rsa_key(self, payload):
        return {
            "code": CODE_RESPONSE_RSA_KEY,
            "pubkey": security.get_publickey()
        }

    def cmd_nopwd_access(self, payload):
        rawdata = security.decrypt_msg(payload)
        ts, pubkey = struct.unpack("<d%ss" % (len(rawdata) - 8), rawdata)

        if not security.validate_timestemp(self.memcache, ts):
            return
        if not security.is_rsakey(pubkey):
            return

        resp = {"code": CODE_RESPONSE_NOPWD_ACCESS,
                "access_id": security.get_access_id(pubkey)}

        if security.is_trusted_publickey(pubkey):
            resp.update({
                "status": "ok",
                "access_id": security.get_access_id(pubkey)})
            if pubkey == self.padding_request_pubkey:
                self.padding_request_pubkey = None
        elif security.has_password():
            resp["status"] = "deny"
        elif self.padding_request_pubkey:
            if pubkey == self.padding_request_pubkey:
                resp["status"] = "padding"
            else:
                resp["status"] = "blocking"
            return resp
        else:
            self.padding_request_pubkey = pubkey
            resp["status"] = "padding"

        return resp

    def cmd_pwd_access(self, payload):
        rawdata = security.decrypt_msg(payload)
        ts, passwd, pubkey = json.loads(rawdata)

        if not security.is_rsakey(pubkey):
            return

        elif security.is_trust_publickey(pubkey):
            return {
                "code": CODE_RESPONSE_PWD_ACCESS,
                "access_id": security.get_access_id(pubkey),
                "status": "ok"}

        elif security.validate_password(self.memcache, passwd, ts):
            access_id = security.add_trust_publickey(pubkey)
            return {
                "code": CODE_RESPONSE_PWD_ACCESS,
                "access_id": access_id,
                "status": "ok"}

    def _parse_signed_request(self, payload):
        # access id (20) + sign_length (2) + timestemp (8) +
        # sign (sing length) + message

        rawdata = security.decrypt_msg(payload)
        # binary_access_id, sign length, timestemp
        ba, sl, timestemp = struct.unpack("<20sHd", rawdata[:30])

        access_id = binascii.b2a_hex(ba)
        signature = rawdata[30:sl + 30]
        message = rawdata[sl + 30:]

        if security.validate_signature(message, signature, access_id):
            if security.validate_timestemp(self.memcache, timestemp):
                return True, access_id, message
        else:
            return False, None, []

    def cmd_change_pwd(self, payload):
        ok, access_id, message = self._parse_signed_request(payload)
        if ok:
            pem = security.get_remote_pubkey(access_id)
            passwd, old_passwd = message.split("\x00", 1)

            if security.set_password(self.memcache, passwd, old_passwd):
                security.add_trust_publickey(pem)
                return {
                    "status": "ok", "timestemp": time(),
                    "code": CODE_RESPONSE_CHANGE_PWD,
                    "access_id": access_id}

            else:
                return {
                    "code": CODE_RESPONSE_CHANGE_PWD,
                    "message": "BAD_PASSWORD",
                    "status": "error", "timestemp": time(),
                }

    def cmd_set_network(self, payload):
        ok, access_id, message = self._parse_signed_request(payload)
        if ok:
            raw_opts = dict([i.split("=", 1) for i in message.split("\x00")])

            options = {"ifname": "wlan0"}
            method = raw_opts.get("method")
            if method == "dhcp":
                options["method"] = "dhcp"
            elif method == "static":
                options.update({
                    "method": "static", "ipaddr": raw_opts["ipaddr"],
                    "mask": raw_opts["mask"], "route": raw_opts["route"],
                    "ns": raw_opts["ns"].split(",")
                })
            else:
                return

            security = raw_opts.get("security", None)
            if security == "WEP":
                options.update({
                    "ssid": raw_opts["ssid"], "security": "WEP",
                    "wepkey": raw_opts["wepkey"]})
            elif security in ['WPA-PSK', 'WPA2-PSK']:
                options.update({
                    "ssid": raw_opts["ssid"],
                    "security": security,
                    "psk": raw_opts["psk"]
                })
            elif "ssid" in raw_opts:
                options["ssid"] = raw_opts["ssid"]

            # TODO Here we has an issue: server must response before change
            # network config, we make a delay call to prevent this problem.
            delay_config_network(json.dumps(["config_network", options]))

            return {
                "status": "ok", "timestemp:": time(),
                "code": CODE_RESPONSE_SET_NETWORK,
                "access_id": access_id}


def delay_config_network(buf):
    from threading import Thread

    def execute(s, b):
        sleep(1.0)
        s.send(b)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.connect(network_config["unixsocket"])
    t = Thread(target=execute, args=(sock, buf))
    t.setDaemon(True)
    t.start()


class UpnpSocket(object):
    def __init__(self, server, port=DEFAULT_PORT):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", port))

        self.sock = sock
        self.server = server

        self._callback = {
            CODE_DISCOVER: self.server.cmd_discover,
            CODE_RSA_KEY: self.server.cmd_rsa_key,
            CODE_NOPWD_ACCESS: self.server.cmd_nopwd_access,
            CODE_PWD_ACCESS: self.server.cmd_pwd_access,
            CODE_CHANGE_PWD: self.server.cmd_change_pwd,
            CODE_SET_NETWORK: self.server.cmd_set_network,
        }

    def fileno(self):
        return self.sock.fileno()

    def on_read(self):
        buf, remote = self.sock.recvfrom(4096)
        if len(buf) < 22:
            return  # drop if payload length too short

        magic_num, bid, code = struct.unpack("<4s16sh", buf[:22])
        serial = _uuid.UUID(bytes=bid).hex
        if magic_num != "FLUX" or \
           (serial != security.get_serial() and serial != GLOBAL_SERIAL.hex):
            return  # drop if payload is wrong syntax

        cb = self._callback.get(code)
        if cb:
            resp = cb(buf[22:])
            if resp:
                message = json.dumps(resp)

                if code == CODE_DISCOVER:
                    payload = message + b"\x00"
                    self.sock.sendto(payload, ("255.255.255.255", remote[1]))
                else:
                    signature = security.sign(message)
                    payload = message + b"\x00" + signature
                    self.sock.sendto(payload, ("255.255.255.255", remote[1]))

    def close(self):
        self.sock.close()


class UpnpWatcher(WatcherBase, UpnpServicesMix, NetworkMonitorMix):
    ipaddress = []
    sock = None

    def __init__(self, memcache):
        super(UpnpWatcher, self).__init__(logger, memcache)

    def _on_status_changed(self, status):
        """Overwrite _on_status_changed witch called by `NetworkMonitorMix`
        when network status changed
        """
        nested = [st.get('ipaddr', [])
                  for _, st in status.items()]
        ipaddress = list(chain(*nested))

        if self.ipaddress != ipaddress:
            self.ipaddress = ipaddress
            self._replace_upnp_sock()

    def _replace_upnp_sock(self):
        self._try_close_upnp_sock()
        if self.ipaddress:
            try:
                self.sock = UpnpSocket(self)
                self.rlist.append(self.sock)
                self.logger.info("Upnp UP")
            except socket.error:
                self.logger.exception("")
                self._try_close_upnp_sock()
        else:
                self.logger.info("Upnp DOWN")

    def _try_close_upnp_sock(self):
        if self.sock:
            if self.sock in self.rlist:
                self.rlist.remove(self.sock)
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

    def run(self):
        self.bootstrap_network_monitor(self.memcache)
        self._on_status_changed(self._monitor.full_status())
        super(UpnpWatcher, self).run()
