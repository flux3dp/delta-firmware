
from signal import signal, SIGCHLD
from itertools import chain
from time import time, sleep
import uuid as _uuid
import subprocess
import binascii
import logging
import struct
import socket
import json

logger = logging.getLogger(__name__)

from fluxmonitor.misc._process import Process
from fluxmonitor.misc import network_config_encoder as NCE
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.config import network_config
from fluxmonitor.misc import control_mutex
from fluxmonitor.storage import Storage
from fluxmonitor.err_codes import ALREADY_RUNNING, BAD_PASSWORD, NOT_RUNNING, \
    RESOURCE_BUSY, AUTH_ERROR, UNKNOW_ERROR

from fluxmonitor import STR_VERSION as VERSION
from fluxmonitor import security
from .base import ServiceBase
from ._network_helpers import NetworkMonitorMix


SERIAL_HEX = security.get_uuid()
MODEL_ID = get_model_id()
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


class UpnpServiceMix(object):
    padding_request_pubkey = None
    robot_agent = None

    def _in_discover_history(self, remote):
        identify = socket.inet_aton(remote[0]) + struct.pack("I", remote[1])
        if identify in self._discover_history:
            ts, counter = self._discover_history[identify]
            counter -= (time() - ts) // 15
            if counter < 0:
                counter = 0

            if counter >= 6:
                self._discover_history[identify] = (ts, counter)
                return True
            else:
                self._discover_history[identify] = (time(), counter + 1)
                return False

        else:
            if len(self._discover_history) > 512:
                min_key, min_ts = None, time()
                for key, val in self._discover_history.items():
                    min_ts = val[0]
                    if ts < min_ts:
                        min_key, min_ts = key, ts
                self._discover_history.pop(key)

            self._discover_history[identify] = (time(), 1)

        return False

    def cmd_discover(self, remote):
        if not self._in_discover_history(remote):
            return {"ver": VERSION, "name": self.meta.get_nickname(),
                    "model": MODEL_ID, "serial": SERIAL_HEX,
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
        b_ts, b_passwd, pubkey = rawdata.split(b"\x00", 2)

        # ts = float(b_ts)
        passwd = b_passwd.decode("utf8")

        keyobj = security.get_keyobj(der=pubkey)
        if not keyobj:
            return

        access_id = security.get_access_id(keyobj=keyobj)
        if security.is_trusted_remote(keyobj=keyobj):
            return {
                "access_id": security.get_access_id(der=pubkey),
                "status": "ok"}

        elif security.validate_password(passwd):
            security.add_trusted_keyobj(keyobj)
            return {"access_id": access_id, "status": "ok"}
        else:
            return {"access_id": access_id, "status": "deny"}

    def cmd_change_pwd(self, access_id, message):
        keyobj = security.get_keyobj(access_id=access_id)
        passwd, old_passwd = message.split("\x00", 1)

        if security.validate_and_set_password(passwd, old_passwd):
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

        nw_config = ("config_network" + "\x00" + \
                     NCE.to_bytes(options)).encode()
        self.add_loop_event(DelayNetworkConfigure(nw_config))

        return {"timestemp": time()}

    def cmd_control_status(self, access_id, message):
        pid = control_mutex.locking_status()
        if pid:
            status = "running"
        else:
            status = "idel"

        return {"timestemp": time(), "onthefly": status}

    def cmd_require_robot(self, access_id, message):
        if self.robot_agent:
            ret = self.robot_agent.poll()
            if ret is None:
                return {"status": "launching"}
            else:
                self.robot_agent = None

                if ret == 0:
                    return {"status": "launched"}
                elif ret == 0x80:
                    return {"status": "launched", "info": "double launch"}
                else:
                    logger.error("Robot daemon return statuscode %i" % ret)
                    raise RuntimeError(UNKNOW_ERROR, "%i" % ret)

        else:
            pid = control_mutex.locking_status()
            if pid:
                return {"status": "launched", "info": "already running"}
            else:
                self.robot_agent = RobotLaunchAgent(self)
                return {"status": "initial"}

        while True:
            ret = daemon.poll()
            if ret == None:
                if time() - timestemp > 16:
                    daemon.kill()
                else:
                    sleep(0.05)
            elif ret == 0:
                return {"timestemp": time()}
            elif ret == 0x80:
                raise RuntimeError(ALREADY_RUNNING)
            else:
                logger.error("Robot daemon return statuscode %i" % ret)
                raise RuntimeError(UNKNOW_ERROR, "%i" % ret)

    def cmd_reset_control(self, access_id, message):
        do_kill = message == b"\x01"
        label = control_mutex.terminate(kill=do_kill)

        if label:
            return {"timestemp": time()}
        else:
            raise RuntimeError(NOT_RUNNING)


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
        """Message struct:
         +-----------+---------+------+-------------+---------+
         | Access ID | TS      | Salt | Body    (n) | sign (k)|
         +-----------+---------+------+-------------+---------+
         0          20        28     32          32+n      32+k
        21+

        Salt: 4 random char, do not send same salt in 15 min
        Access ID: sha1 hash for public key
        TS: Timestemp
        Body: as title (length n)
        Sign: signature (length k), signature range: 'serial(16) + 0 ~ (28+n)'
        """

        message = self.server.pkey.decrypt(payload[21:])

        bin_access_id, ts, salt = struct.unpack("<20sdi", message[:32])

        # Check client key
        access_id = binascii.b2a_hex(bin_access_id)
        cli_keyobj = security.get_keyobj(access_id=access_id)
        cli_keylen = cli_keyobj.size()
        body, sign = message[:-cli_keylen], message[-cli_keylen:]

        serial = payload[4:20]
        cli_keylen = cli_keyobj.size()

        if not cli_keyobj:
            logger.debug("Access id '%s' not found" % access_id)
            return False, access_id, None

        if not cli_keyobj.verify(serial + body, sign):
            logger.debug("Signuture error for '%s'" % access_id)
            return False, access_id, None

        # Check Timestemp
        if not security.validate_timestemp((ts, salt)):
            logger.debug("Timestemp error for '%s' (salt=%i, d=%.2f)" % ( 
                         access_id, salt, time() - ts))
            return False, access_id, None

        return True, access_id, body[32:]

    def on_read(self, sender):
        """Payload struct:
        +----+---------------+----+
        | MN | Device Serial | OP |
        +----+---------------+----+
        0    4              20   21

        MN: Magic Number, always be "FLUX"
        Device Serial: device 16 (binary format). be 0 for broadcase.
        OP: Request code, looks for CODE_* consts
        """
        buf, remote = self.sock.recvfrom(4096)
        if len(buf) < 21:
            return  # drop if payload length too short

        magic_num, bserial, code = struct.unpack("<4s16sB", buf[:21])
        serial = _uuid.UUID(bytes=bserial).hex
        if magic_num != "FLUX" or \
           (serial != SERIAL_HEX and serial != GLOBAL_SERIAL.hex):
            return  # drop if payload is wrong syntax

        self.handle_request(code, buf, remote)

    def handle_request(self, request_code, buf, remote):
        callback = self._callback.get(request_code)
        if not callback:
            logger.debug("Recive unhandle request code: %i" % request_code)
            return

        try:
            t1 = time()
            if request_code == 0x00:
                message = callback(remote)
                if message:
                    resp = json.dumps(message)
                    self.send_response(request_code, 0, resp, remote, False)
                else:
                    return
            elif request_code < 0x80:
                response = json.dumps(callback(buf[21:]))
                self.send_response(request_code, 0, response, remote, True)
            else:
                ok, access_id, message = self.parse_signed_request(buf)
                if ok:
                    response = json.dumps(callback(access_id, message))
                    self.send_response(request_code, 0, response, remote, True)
                else:
                    raise RuntimeError(AUTH_ERROR)

            logger.debug("Handle request 0x%x (%f)" % (request_code,
                                                       time() - t1))
        except RuntimeError as e:
            self.send_response(request_code, 1, e.args[0], remote, True)

        except Exception as e:
            logger.exception("Unhandle exception")

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


class UpnpService(ServiceBase, UpnpServiceMix, NetworkMonitorMix):
    _discover_history = None
    ipaddress = None
    sock = None

    def __init__(self, options):
        self.debug = options.debug

        self._discover_history = {}
        self.meta = CommonMetadata()

        # Create RSA key if not exist. This will prevent upnp create key during
        # upnp is running (Its takes times and will cause timeout)
        self.pkey = security.get_private_key()
        self.pubkey_pem = self.pkey.export_pubkey_pem()

        super(UpnpService, self).__init__(logger)

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
            self.add_read_event(self.sock)
            self.logger.info("Upnp going UP")
        except socket.error:
            self.logger.exception("")
            self._try_close_upnp_sock()

    def _try_close_upnp_sock(self):
        if self.sock:
            self.logger.info("Upnp going DOWN")
            self.remove_read_event(self.sock)
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def on_start(self):
        self.bootstrap_network_monitor(self.memcache)
        self._on_status_changed(self._monitor.full_status())

    def on_shutdown(self):
        self._try_close_upnp_sock()

    def each_loop(self):
        pass


class RobotLaunchAgent(Process):
    
    @classmethod
    def init(cls, service):
        logfile = Storage("log").get_path("robot.log")
        pidfile = control_mutex.pidfile()
        return cls(services, ["fluxrobot", "--pid", pidfile, "--log", logfile,
                              "--daemon"],
                   )
        daemon = subprocess.Popen(["fluxrobot", "--pid", pidfile, "--log",
                                   logfile, "--daemon"], close_fds=True)

    def __init__(self, services):
        pid = control_mutex.locking_status()
        if pid:
            raise RuntimeError(ALREADY_RUNNING)

        logfile = Storage("log").get_path("robot.log")
        pidfile = control_mutex.pidfile()

        Process.__init__(self, services, ["fluxrobot", "--pid", pidfile,
                                          "--log", logfile, "--daemon"])

    def on_daemon_closed(self):
        timestemp = time()

        ret = self.poll()
        while ret == None and (time() - timestemp) < 3:
            sleep(0.05)
            ret = self.poll()

        if ret == None:
            self.kill()


class DelayNetworkConfigure(object):
    def __init__(self, config):
        self.config = config

    def on_loop(self, caller):
        caller.remove_loop_event(self)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(network_config["unixsocket"])
        sock.send(self.config)
        sock.close()
