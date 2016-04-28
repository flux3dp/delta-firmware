
from itertools import chain
from time import time
import uuid as _uuid
import binascii
import logging
import struct
import socket
import json

import pyev

from fluxmonitor.hal.net.monitor import Monitor as NetworkMonitor
from fluxmonitor.interfaces.upnp_tcp import UpnpTcpInterface
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.err_codes import BAD_PASSWORD, AUTH_ERROR
from fluxmonitor.storage import Metadata
from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT
from fluxmonitor.misc import network_config_encoder as NCE  # noqa

from fluxmonitor import __version__ as VERSION  # noqa
from fluxmonitor import security
from .base import ServiceBase

logger = logging.getLogger(__name__)


SERIAL_HEX = security.get_uuid()
SERIAL_BIN = binascii.a2b_hex(SERIAL_HEX)
SERIAL_NUMBER = security.get_serial()
UUID_BYTES = SERIAL_BIN
MODEL_ID = get_model_id()


CODE_NOPWD_ACCESS = 0x04
CODE_PWD_ACCESS = 0x06

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


class InterfaceBaseV1(object):
    __notify_payload = None
    __touch_payload = None

    def __init__(self, server):
        self.server = server
        self.meta = server.meta
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                  socket.IPPROTO_UDP)

    def fileno(self):
        return self.sock.fileno()

    @property
    def _notify_payload(self):
        if not self.__notify_payload:
            slave_pkey_ts = self.server.slave_pkey_ts
            main_pubder = self.server.master_key.export_pubkey_der()
            identify = security.get_identify()

            self.__notify_payload = struct.pack(
                "<4sBB16s10sfHH",
                "FLUX",             # Magic String
                1,                  # Protocol Version
                0,                  # Discover Code
                UUID_BYTES,         # Device UUID
                SERIAL_NUMBER,      # Device Serial Number
                slave_pkey_ts,      # TEMP TS
                len(main_pubder),   # Public Key length
                len(identify),      # Identify length
            ) + main_pubder + identify
        return self.__notify_payload + self.meta.device_status

    @property
    def _touch_payload(self):
        if not self.__touch_payload:
            temp_ts = self.server.slave_pkey_ts
            temp_pkey_der = self.server.slave_pkey.export_pubkey_der()
            temp_pkey_sign = self.server.master_key.sign(
                struct.pack("<f", temp_ts) + temp_pkey_der)

            self.__touch_payload = struct.pack(
                "<4sBB16sfHH",
                "FLUX",              # Magic String
                1,                   # Protocol Version
                3,                   # Tocuh Code
                UUID_BYTES,          # Device UUID
                temp_ts,
                len(temp_pkey_der),  # Temp pkey length
                len(temp_pkey_sign)  # Temp pkey sign
            ) + temp_pkey_der + temp_pkey_sign
        return self.__touch_payload

    def send_notify_to(self, endpoint):
        self.sock.sendto(self._notify_payload, endpoint)

    def on_touch(self, endpoint):
        info = "ver=%s\x00model=%s\x00name=%s\x00pwd=%s\x00time=%i" % (
            VERSION, MODEL_ID, self.meta.nickname,
            "T" if security.has_password() else "F",
            time()
        )

        payload = self._touch_payload + struct.pack("<H", len(info)) + info + \
            self.server.slave_pkey.sign(info)

        self.sock.sendto(payload, endpoint)

    def on_message(self, watcher, revent):
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
            if action_id == 0 and buuid == GLOBAL_SERIAL.bytes:
                self.send_notify_to(endpoint)

    def send_response(self, endpoint, action_id, message):
        payload = struct.pack("<4sBB16sH", b"FLUX", 1, action_id + 1,
                              UUID_BYTES, len(message))
        signature = self.server.slave_pkey.sign(message)
        self.sock.sendto(payload + message + signature, endpoint)

    def close(self):
        self.sock.close()


class InterfaceBaseV2(InterfaceBaseV1):
    __notify_payload = None

    @property
    def _notify_payload(self):
        if not self.__notify_payload:
            self.__notify_payload = struct.pack(
                "<4sBB16s",
                "FLUX",             # Magic String
                2,                  # Protocol Version
                0,                  # Discover Code
                UUID_BYTES)         # Device UUID
        return self.__notify_payload + self.meta.device_status


class BroadcaseNotifyInterface(InterfaceBaseV2):
    def __init__(self, server, sendto=("255.255.255.255", 1902)):
        super(BroadcaseNotifyInterface, self).__init__(server)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.endpoint = sendto

    def send_notify(self):
        self.sock.sendto(self._notify_payload, self.endpoint)

    def close(self):
        self.sock.close()


class MulticaseNotifyInterface(InterfaceBaseV1):
    def __init__(self, server, sendto=("239.255.255.250", 1901)):
        super(MulticaseNotifyInterface, self).__init__(server)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.endpoint = sendto

    def send_notify(self):
        self.sock.sendto(self._notify_payload, self.endpoint)

    def send_notify_to(self, endpoint):
        self.sock.sendto(self._notify_payload + self.meta.device_status,
                         endpoint)


class UnicasetInterface(InterfaceBaseV1):
    def __init__(self, server, ipaddr="", port=1901):
        super(UnicasetInterface, self).__init__(server)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # mreq = struct.pack("4sl", socket.inet_aton(addr),
        #                    socket.INADDR_ANY)
        # self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
        #                      mreq)
        self.sock.bind((ipaddr, port))


class UpnpServiceMixIn(object):
    padding_request_pubkey = None

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
        rawdata = self.slave_pkey.decrypt(payload)
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

        self.task_signal.data = DelayNetworkConfigure(nw_config)
        self.task_signal.send()

        return {"timestemp": time()}


class UpnpService(ServiceBase, UpnpServiceMixIn):
    bcst = None
    mcst = None
    ucst = None
    ucst_watcher = None
    cron_watcher = None
    ipaddress = None

    def __init__(self, options):
        # Create RSA key if not exist. This will prevent upnp create key during
        # upnp is running (Its takes times and will cause timeout)
        self.master_key = security.get_private_key()
        self.slave_pkey = security.RSAObject(keylength=1024)
        self.slave_pkey_ts = time()

        self.meta = Metadata()
        self.meta.shared_der_rsakey = self.slave_pkey.export_der()
        self.meta.update_device_status(0, 0, "OFFLINE", "")

        self._callback = {
            CODE_NOPWD_ACCESS: self.cmd_nopwd_access,
            CODE_PWD_ACCESS: self.cmd_pwd_access,
            CODE_CHANGE_PWD: self.cmd_change_pwd,
            CODE_SET_NETWORK: self.cmd_set_network,
        }

        super(UpnpService, self).__init__(logger)

        self.upnp_tcp = UpnpTcpInterface(self)

        self.task_signal = self.loop.async(self.on_delay_task)
        self.task_signal.start()

        self.nw_monitor = NetworkMonitor(None)
        self.nw_monitor_watcher = self.loop.io(self.nw_monitor, pyev.EV_READ,
                                               self.on_network_changed)
        self.nw_monitor_watcher.start()
        self.cron_watcher = self.loop.timer(3.0, 3.0, self.on_cron)
        self.cron_watcher.start()

    def on_auth(self, keyobj, passwd, add_key=True):
        passwd = passwd.decode("utf8")
        access_id = security.get_access_id(keyobj=keyobj)

        if security.validate_password(passwd):
            if add_key:
                security.add_trusted_keyobj(keyobj)
            return access_id
        else:
            return None

    def on_modify_passwd(self, keyobj, old_passwd, new_passwd, reset_acl):
        ret = security.validate_and_set_password(new_passwd, old_passwd,
                                                 reset_acl)
        if ret:
            security.add_trusted_keyobj(keyobj)

        return ret

    def on_modify_network(self, raw_config):
        config = NCE.validate_options(raw_config)
        nw_config = ("config_network" + "\x00" +
                     NCE.to_bytes(config)).encode()

        self.task_signal.data = DelayNetworkConfigure(nw_config)
        self.task_signal.send()

    def on_network_changed(self, watcher, revent):
        if self.nw_monitor.read():
            status = self.nw_monitor.full_status()
            nested = [st.get('ipaddr', [])
                      for _, st in status.items()]
            ipaddress = list(chain(*nested))

            if self.ipaddress != ipaddress:
                self.ipaddress = ipaddress
                if watcher:
                    self._replace_upnp_sock()
                else:
                    self._try_open_upnp_sock()

    def on_rename_device(self, new_name):
        self.meta.nickname = new_name

    def _replace_upnp_sock(self):
        self._try_close_upnp_sock()
        self._try_open_upnp_sock()

    def _try_open_upnp_sock(self):
        try:
            self.logger.debug("Upnp going UP")

            mcst_if = MulticaseNotifyInterface(self)
            mcst_watcher = self.loop.io(mcst_if, pyev.EV_READ,
                                        mcst_if.on_message)
            mcst_watcher.start()
            self.mcst = (mcst_if, mcst_watcher)

            ucst_if = UnicasetInterface(self)
            ucst_watcher = self.loop.io(ucst_if, pyev.EV_READ,
                                        ucst_if.on_message)
            ucst_watcher.start()
            self.ucst = (ucst_if, ucst_watcher)

            if self.meta.broadcast == "on":
                bcst_if = BroadcaseNotifyInterface(self)
                bcst_watcher = self.loop.io(bcst_if, pyev.EV_READ,
                                            bcst_if.on_message)
                self.bcst = (bcst_if, bcst_watcher)
        except socket.error:
            self.logger.exception("Error while upnp going UP")
            self._try_close_upnp_sock()

    def _try_close_upnp_sock(self):
        self.logger.debug("Upnp going DOWN")
        if self.ucst:
            ifce, watcher = self.ucst
            watcher.stop()
            ifce.close()
            self.ucst = None

        if self.mcst:
            ifce, watcher = self.mcst
            watcher.stop()
            ifce.close()
            self.mcst = None

        if self.bcst:
            ifce, watcher = self.bcst
            watcher.stop()
            ifce.close()
            self.bcst = None

    def on_start(self):
        self.on_network_changed(None, None)

    def on_shutdown(self):
        self._try_close_upnp_sock()

    def on_cron(self, watcher, revent):
        if self.mcst:
            self.mcst[0].send_notify()
        if self.bcst:
            self.bcst[0].send_notify()

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
                ok, access_id, message = parse_signed_request(
                    payload, self.slave_pkey)
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

    def on_delay_task(self, watcher, revent):
        if watcher.data:
            watcher.data.fire()
            watcher.data = None


class DelayNetworkConfigure(object):
    def __init__(self, config):
        self.config = config

    def fire(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(NETWORK_MANAGE_ENDPOINT)
        sock.send(self.config)
        sock.close()
