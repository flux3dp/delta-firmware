
from itertools import chain
from time import time
import uuid as _uuid
import subprocess
import binascii
import logging
import struct
import socket
import json

logger = logging.getLogger(__name__)

from fluxmonitor.config import network_config
from fluxmonitor.misc import control_mutex
from fluxmonitor.err_codes import ALREADY_RUNNING, BAD_PASSWORD, NOT_RUNNING, \
    RESOURCE_BUSY

from fluxmonitor import STR_VERSION as VERSION
from fluxmonitor import security
from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix

MODEL = "flux3dp:1"
DEFAULT_PORT = 3310


CODE_DISCOVER = 0x00
CODE_RSA_KEY = 0x02
CODE_NOPWD_ACCESS = 0x04
CODE_PWD_ACCESS = 0x06

CODE_CONTROL_STATUS = 0x80
CODE_RESET_CONTROL = 0x82
CODE_REQUEST_ROBOT = 0x84
CODE_CHANGE_PWD = 0xa0
CODE_SET_NETWORK = 0xa2


GLOBAL_SERIAL = _uuid.UUID(int=0)


class UpnpServicesMix(object):
    padding_request_pubkey = None

    network_config_buf = None

    def cmd_discover(self, payload):
        """Return IP Address in array"""
        # TODO: NOT CONFIRM
        return {"ver": VERSION,
                "model": MODEL, "serial": security.get_serial(),
                "time": time(), "ip": self.ipaddress,
                "pwd": security.has_password()}

    def cmd_rsa_key(self, payload):
        return self.pubkey_pem

    def cmd_nopwd_access(self, payload):
        if len(payload) < 64:
            return

        ts, pubkey = struct.unpack("<d%ss" % (len(payload) - 8), payload)

        resp = {"access_id": security.get_access_id(der=pubkey)}

        keyobj = security.get_keyobj(der=pubkey)

        if security.is_trusted_remote(keyobj=keyobj):
            resp.update({
                "status": "ok",
                "access_id": security.get_access_id(der=pubkey)})
            if pubkey == self.padding_request_pubkey:
                self.padding_request_pubkey = None
        elif security.has_password():
            resp["status"] = "deny"
        elif self.padding_request_pubkey:
            if pubkey == self.padding_request_pubkey:
                resp["status"] = "padding"
            else:
                resp["status"] = "blocking"
        else:
            if keyobj:
                self.padding_request_pubkey = pubkey
                resp["status"] = "padding"
        return resp

    def cmd_pwd_access(self, payload):
        rawdata = self.pkey.decrypt(payload)
        ts, passwd, pubkey = json.loads(rawdata)

        keyobj = security.get_keyobj(der=pubkey)
        if not keyobj:
            return

        access_id = security.get_access_id(keyobj=keyobj)
        if security.is_trusted_remote(keyobj=keyobj):
            return {
                "access_id": security.get_access_id(pubkey),
                "status": "ok"}

        elif security.validate_password(self.memcache, passwd):
            return {"access_id": access_id, "status": "ok"}
        else:
            return {"access_id": access_id, "status": "deny"}

    def cmd_change_pwd(self, access_id, message):
        keyobj = security.get_keyobj(access_id=access_id)
        passwd, old_passwd = message.split("\x00", 1)

        if security.set_password(self.memcache, passwd, old_passwd):
            security.add_trusted_keyobj(keyobj)
            return {"timestemp": time()}

        else:
            raise RuntimeError(BAD_PASSWORD)

    def cmd_set_network(self, access_id, message):
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

        self.network_config_buf = json.dumps(["config_network", options])

        return {"timestemp:": time()}

    def cmd_control_status(self, access_id, message):
        _, label = control_mutex.locking_status()
        if not label:
            label = "idel"

        return {"timestemp:": time(), "onthefly": label}

    def cmd_require_robot(self, access_id, message):
        pid, label = control_mutex.locking_status()

        if label == "robot":
            raise RuntimeError(ALREADY_RUNNING)
        elif pid:
            raise RuntimeError(RESOURCE_BUSY)

        # TODO: not good
        subprocess.Popen(["fluxrobot"])

        return {"timestemp:": time()}

    def cmd_reset_control(self, access_id, message):
        do_kill = message == b"\x01"
        label = control_mutex.terminate(kill=do_kill)

        if label:
            return {"task": label}
        else:
            raise RuntimeError(NOT_RUNNING)

    def _clean_network_config_buf(self):
        if self.network_config_buf:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.connect(network_config["unixsocket"])
            sock.send(self.network_config_buf)
            self.network_config_buf = None


class UpnpSocket(object):
    def __init__(self, server, ipaddr, port=DEFAULT_PORT):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((ipaddr, port))

        self.sock = sock
        self.server = server

        self._callback = {
            CODE_DISCOVER: self.server.cmd_discover,
            CODE_RSA_KEY: self.server.cmd_rsa_key,
            CODE_NOPWD_ACCESS: self.server.cmd_nopwd_access,
            CODE_PWD_ACCESS: self.server.cmd_pwd_access,
            CODE_CHANGE_PWD: self.server.cmd_change_pwd,
            CODE_SET_NETWORK: self.server.cmd_set_network,

            CODE_CONTROL_STATUS: self.server.cmd_control_status,
            CODE_RESET_CONTROL: self.server.cmd_reset_control,
            CODE_REQUEST_ROBOT: self.server.cmd_require_robot
        }

    def fileno(self):
        return self.sock.fileno()

    def get_remote_sockname(self, orig):
        if orig[0] == "127.0.0.1":
            return ("127.0.0.1", orig[1])
        else:
            return ("255.255.255.255", orig[1])

    def parse_signed_request(self, payload):
        rawdata = self.server.pkey.decrypt(payload)

        # access id (20) + sign (sing length) + (timestemp (8) + message)
        access_id = binascii.b2a_hex(rawdata[:20])
        client_keyobj = security.get_keyobj(access_id=access_id)

        if client_keyobj:
            keylen = client_keyobj.size()

            signature = rawdata[20:20 + keylen]
            timestemp = struct.unpack("<d",
                                      rawdata[20 + keylen:28 + keylen])[0]
            message = rawdata[28 + keylen:]

            if client_keyobj.verify(rawdata[20 + keylen:], signature):
                if security.validate_timestemp(self.server.memcache,
                                               (timestemp, signature)):
                    return True, access_id, message

        return False, None, None

    def on_read(self):
        buf, remote = self.sock.recvfrom(4096)
        if len(buf) < 21:
            return  # drop if payload length too short

        magic_num, bid, code = struct.unpack("<4s16sB", buf[:21])
        serial = _uuid.UUID(bytes=bid).hex
        if magic_num != "FLUX" or \
           (serial != security.get_serial() and serial != GLOBAL_SERIAL.hex):
            return  # drop if payload is wrong syntax

        self.handle_request(code, buf[21:], remote)

    def handle_request(self, request_code, raw_msg, remote):
        callback = self._callback.get(request_code)
        if not callback:
            logger.debug("Recive unhandle request code: %i" % request_code)
            return

        try:
            t1 = time()
            if request_code == 0x00:
                response = json.dumps(callback(raw_msg))
                self.send_response(request_code, 0, response, remote, False)
            elif request_code < 0x80:
                response = json.dumps(callback(raw_msg))
                self.send_response(request_code, 0, response, remote, True)
            else:
                ok, access_id, message = self.parse_signed_request(raw_msg)
                if ok:
                    response = json.dumps(callback(access_id, message))
                    self.send_response(request_code, 0, response, remote, True)
                else:
                    logger.debug("Bad client from %s" % remote[0])
            logger.debug("Handle request %x (%f)" % (request_code, 
                                                     time() - t1))
        except RuntimeError as e:
            self.send_response(request_code, 1, e.args[0], remote, True)

    def send_response(self, request_code, response_code, message, remote,
                      require_sign):
        header = struct.pack("<BB", request_code + 1, response_code)
        if require_sign:
            signature = self.server.pkey.sign(message)
            buf = header + b"\x00".join((message, signature))
        else:
            buf = header + message + b"\x00"

        self.sock.sendto(buf, self.get_remote_sockname(remote))

    def close(self):
        self.sock.close()


class UpnpWatcher(WatcherBase, UpnpServicesMix, NetworkMonitorMix):
    ipaddress = None
    sock = None

    def __init__(self, server):
        # Create RSA key if not exist. This will prevent upnp create key during
        # upnp is running (Its takes times and will cause timeout)
        self.pkey = security.get_private_key()
        self.pubkey_pem = self.pkey.export_pubkey_pem()

        super(UpnpWatcher, self).__init__(server, logger)

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
        ipaddr = "" if self.ipaddress else "127.0.0.1"

        try:
            self.sock = UpnpSocket(self, ipaddr=ipaddr)
            self.server.add_read_event(self.sock)
            self.logger.info("Upnp going UP")
        except socket.error:
            self.logger.exception("")
            self._try_close_upnp_sock()

    def _try_close_upnp_sock(self):
        if self.sock:
            self.logger.info("Upnp going DOWN")
            self.server.remove_read_event(self.sock)
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def start(self):
        self.bootstrap_network_monitor(self.memcache)
        self._on_status_changed(self._monitor.full_status())

    def shutdown(self):
        pass

    def each_loop(self):
        self._clean_network_config_buf()
