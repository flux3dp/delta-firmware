
from itertools import chain
from time import time, sleep
import uuid as _uuid
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

from fluxmonitor import __version__ as VERSION
from fluxmonitor import security
from .base import ServiceBase
from ._network_helpers import NetworkMonitorMix


SERIAL_HEX = security.get_uuid()
SERIAL_BIN = binascii.a2b_hex(SERIAL_HEX)
SERIAL_NUMBER = security.get_serial()
UUID_BYTES = SERIAL_BIN
MULTICAST_VERSION = 1
MODEL_ID = get_model_id()


CODE_NOPWD_ACCESS = 0x04
CODE_PWD_ACCESS = 0x06

CODE_CONTROL_STATUS = 0x80
CODE_RESET_CONTROL = 0x82
CODE_REQUEST_ROBOT = 0x84
CODE_CHANGE_PWD = 0xa0
CODE_SET_NETWORK = 0xa2


GLOBAL_SERIAL = _uuid.UUID(int=0)


def json_payload_wrapper(fn):
    def wrapper(*args, **kw):
        data = fn(*args, **kw)
        if data is not None:
            data["ts"] = time()
        return json.dumps(data)
    return wrapper


def parse_signed_request(payload, secretkey):
    """Message struct:
     +-----------+---------+------+-------------+---------+
     | Access ID | TS      | Salt | Body    (n) | sign (k)|
     +-----------+---------+------+-------------+---------+
     0          20        28     32          32+n      32+k

    Salt: 4 random char, do not send same salt in 15 min
    Access ID: sha1 hash for public key
    TS: Timestemp
    Body: as title (length n)
    Sign: signature (length k), signature range: 'uuid + 0 ~ (32 + n)'
    """

    message = secretkey.decrypt(payload)
    bin_access_id, ts, salt = struct.unpack("<20sdi", message[:32])

    # Check client key
    access_id = binascii.b2a_hex(bin_access_id)
    cli_keyobj = security.get_keyobj(access_id=access_id)
    cli_keylen = cli_keyobj.size()
    body, sign = message[:-cli_keylen], message[-cli_keylen:]

    cli_keylen = cli_keyobj.size()

    if not cli_keyobj:
        logger.debug("Access id '%s' not found" % access_id)
        return False, access_id, None

    if not cli_keyobj.verify(UUID_BYTES + body, sign):
        logger.debug("Signuture error for '%s'" % access_id)
        return False, access_id, None

    # Check Timestemp
    if not security.validate_timestemp((ts, salt)):
        logger.debug("Timestemp error for '%s' (salt=%i, d=%.2f)" % (
                     access_id, salt, time() - ts))
        return False, access_id, None

    return True, access_id, body[32:]


class BroadcastInterface(object):
    def __init__(self, server, ipaddr, port=3310):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((ipaddr, port))

        self.sock = sock
        self.server = server

    def fileno(self):
        return self.sock.fileno()

    def get_remote_sockname(self, orig):
        if orig[0] == "127.0.0.1":
            return ("127.0.0.1", orig[1])
        else:
            return ("255.255.255.255", orig[1])

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

        payload = {"ver": VERSION, "name": self.server.meta.nickname,
                   "model": MODEL_ID, "serial": SERIAL_HEX,
                   "time": time(), "ip": self.server.ipaddress,
                   "pwd": security.has_password()}
        self.send_response(remote, 0, 0, json.dumps(payload))

    def send_response(self, remote, request_code, response_code, message):
        header = struct.pack("<BB", request_code + 1, response_code)
        buf = header + message + b"\x00"
        self.sock.sendto(buf, self.get_remote_sockname(remote))

    def close(self):
        self.sock.close()


class MulticastInterface(object):
    temp_rsakey = None
    timer = 0

    def __init__(self, server, pkey, meta, addr='239.255.255.250', port=1901):
        self.server = server
        self.pkey = pkey
        self.meta = meta
        self.poke_counter = {}

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                  socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        self.mcst_addr = (addr, port)

        self._generate_discover_info()

    def _generate_discover_info(self):
        self.temp_pkey = security.RSAObject(keylength=1024)
        temp_ts = time()
        temp_pkey_der = self.temp_pkey.export_pubkey_der()

        temp_pkey_sign = self.pkey.sign(
            struct.pack("<f", temp_ts) + temp_pkey_der)

        self.meta.shared_der_rsakey = temp_pkey_der

        main_pubder = self.pkey.export_pubkey_der()
        identify = security.get_identify()

        self._discover_payload = struct.pack(
            "<4sBB16s10sfHH",
            "FLUX",             # Magic String
            MULTICAST_VERSION,  # Protocol Version
            0,                  # Discover Code
            UUID_BYTES,         # Device UUID
            SERIAL_NUMBER,      # Device Serial Number
            temp_ts,            # TEMP TS
            len(main_pubder),   # Public Key length
            len(identify),      # Identify length
        ) + main_pubder + identify

        self._touch_payload = struct.pack(
            "<4sBB16sfHH",
            "FLUX",              # Magic String
            MULTICAST_VERSION,   # Protocol Version
            3,                   # Tocuh Code
            UUID_BYTES,          # Device UUID
            temp_ts,
            len(temp_pkey_der),  # Temp pkey length
            len(temp_pkey_sign)  # Temp pkey sign
        ) + temp_pkey_der + temp_pkey_sign

    def reduce_drop_request(self):
        for key in self.poke_counter.keys():
            val = self.poke_counter[key]
            if val > 1:
                self.poke_counter[key] = val -1
            else:
                self.poke_counter.pop(key)

    def drop_request(self, endpoint, action_id):
        key = "%s+%i" % (endpoint[0], action_id)

        val = self.poke_counter.get(key, 0)
        if val > 15:
            return True
        else:
            self.poke_counter[key] = val + 3
            return False

    def on_touch(self, endpoint):
        info = "ver=%s\x00model=%s\x00name=%s\x00pwd=%s\x00time=%i" % (
            VERSION, MODEL_ID, self.meta.nickname,
            "T" if security.has_password() else "F",
            time()
        )

        payload = self._touch_payload + struct.pack("<H", len(info)) + info + \
            self.temp_pkey.sign(info)

        self.sock.sendto(payload, endpoint)

    def fileno(self):
        return self.sock.fileno()

    def on_read(self, kernel):
        """Payload struct:
        +----+-+-+--------+
        | MN |V|A| UUID   |
        |    |R|I|        |
        +----+-+-+--------+
        0    4 5 6       22

        MN: Magic Number, always be "FLUX"
        VR: Protocol Version
        AI: Action ID
        Device Serial: device 16 (binary format). be 0 for broadcase.
        OP: Request code, looks for CODE_* consts
        """

        t1 = time()
        buf, endpoint = self.sock.recvfrom(4096)

        if len(buf) < 22:
            return  # drop if payload length too short

        magic_num, proto_ver, action_id, buuid = struct.unpack("<4sBB16s",
                                                               buf[:22])
        if self.drop_request(endpoint, action_id):
            logger.debug("Drop %s request %i", endpoint[0], action_id)
            return

        if magic_num != b"FLUX":
            return

        if buuid == UUID_BYTES:
            if action_id == 2:
                self.on_touch(endpoint)
            else:
                self.server.on_request(endpoint, action_id, buf[22:], self)
            logger.debug("%s request 0x%x (t=%f)" % (
                endpoint[0], action_id, time() - t1))
        else:
            # UUID not match, ignore message
            return

    def send_response(self, endpoint, action_id, message):
        payload = struct.pack("<4sBB16sH", b"FLUX", 1, action_id + 1,
                              UUID_BYTES, len(message))
        signature = self.temp_pkey.sign(message)
        self.sock.sendto(payload + message + signature, endpoint)

    def send_discover(self):
        if time() - self.timer > 5:
            self.reduce_drop_request()
            self.sock.sendto(self._discover_payload, self.mcst_addr)
            self.timer = time()


class UpnpServiceMixIn(object):
    padding_request_pubkey = None
    robot_agent = None

    @json_payload_wrapper
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

    @json_payload_wrapper
    def cmd_pwd_access(self, payload):
        # TODO: NOT GOOD
        rawdata = self.mcst.temp_pkey.decrypt(payload)
        b_ts, b_passwd, pubkey = rawdata.split(b"\x00", 2)

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

    @json_payload_wrapper
    def cmd_change_pwd(self, access_id, message):
        keyobj = security.get_keyobj(access_id=access_id)
        passwd, old_passwd = message.split("\x00", 1)

        if security.validate_and_set_password(passwd, old_passwd):
            security.add_trusted_keyobj(keyobj)
            return {}

        else:
            raise RuntimeError(BAD_PASSWORD)

    @json_payload_wrapper
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

        nw_config = ("config_network" + "\x00" +
                     NCE.to_bytes(options)).encode()
        self.add_loop_event(DelayNetworkConfigure(nw_config))

        return {"timestemp": time()}

    @json_payload_wrapper
    def cmd_control_status(self, access_id, message):
        pid = control_mutex.locking_status()
        if pid:
            status = "running"
        else:
            status = "idel"

        return {"timestemp": time(), "onthefly": status}

    @json_payload_wrapper
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

    @json_payload_wrapper
    def cmd_reset_control(self, access_id, message):
        do_kill = message == b"\x01"
        label = control_mutex.terminate(kill=do_kill)

        if label:
            return {}
        else:
            raise RuntimeError(NOT_RUNNING)


class UpnpService(ServiceBase, UpnpServiceMixIn, NetworkMonitorMix):
    ipaddress = None
    sock = None

    def __init__(self, options):
        self.debug = options.debug

        # Create RSA key if not exist. This will prevent upnp create key during
        # upnp is running (Its takes times and will cause timeout)
        self.pkey = security.get_private_key()
        self.meta = CommonMetadata()
        self.mcst = MulticastInterface(self, self.pkey, self.meta)

        self._callback = {
            CODE_NOPWD_ACCESS: self.cmd_nopwd_access,
            CODE_PWD_ACCESS: self.cmd_pwd_access,
            CODE_CHANGE_PWD: self.cmd_change_pwd,
            CODE_SET_NETWORK: self.cmd_set_network,

            CODE_CONTROL_STATUS: self.cmd_control_status,
            CODE_RESET_CONTROL: self.cmd_reset_control,
            CODE_REQUEST_ROBOT: self.cmd_require_robot
        }

        super(UpnpService, self).__init__(logger)
        self.add_read_event(self.mcst)

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
            self.sock = BroadcastInterface(self, ipaddr=ipaddr)
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
        self.mcst.send_discover()

    def on_request(self, remote, request_code, payload, interface):
        callback = self._callback.get(request_code)
        if not callback:
            logger.debug("Recive unhandle request code: %i" % request_code)
            return

        try:
            if request_code < 0x80:
                data = callback(payload)
                if data:
                    interface.send_response(remote, request_code, data)
            else:
                # TODO: temp_pkey position not good
                ok, access_id, message = parse_signed_request(
                    payload, self.mcst.temp_pkey)
                if ok:
                    data = callback(access_id, message)
                    if data:
                        interface.send_response(remote, request_code, data)
                else:
                    raise RuntimeError(AUTH_ERROR)

        except RuntimeError as e:
            data = ("E" + e.args[0]).encode()
            interface.send_response(remote, request_code, data)

        except Exception as e:
            logger.exception("Unhandle exception")


class RobotLaunchAgent(Process):
    @classmethod
    def init(cls, service):
        logfile = Storage("log").get_path("robot.log")
        pidfile = control_mutex.pidfile()

        return cls(service, ["fluxrobot", "--pid", pidfile, "--log", logfile,
                             "--daemon"])

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
        while ret is None and (time() - timestemp) < 3:
            sleep(0.05)
            ret = self.poll()

        if ret is None:
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
