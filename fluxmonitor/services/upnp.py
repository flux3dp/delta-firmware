
from itertools import chain
from uuid import UUID
import binascii
import logging
import struct
import socket
import os

import pyev

from fluxmonitor.hal.net.monitor import Monitor as NetworkMonitor
from fluxmonitor.interfaces.upnp_tcp import UpnpTcpInterface
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.storage import Storage, Metadata

from fluxmonitor import __version__ as VERSION  # noqa
from fluxmonitor import security
from .base import ServiceBase

logger = logging.getLogger(__name__)


SERIAL_HEX = security.get_uuid()
SERIAL_BIN = binascii.a2b_hex(SERIAL_HEX)
SERIAL_NUMBER = security.get_serial()
UUID_BYTES = SERIAL_BIN
MODEL_ID = get_model_id()

GLOBAL_SERIAL = UUID(int=0)


class InterfaceBaseV1(object):
    PROTO_VER = 1
    _notify_payload_buf = None
    _touch_payload_buf = None

    def __init__(self, server):
        self.server = server
        self.meta = server.meta
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                  socket.IPPROTO_UDP)

    def fileno(self):
        return self.sock.fileno()

    @property
    def _notify_payload(self):
        if not self._notify_payload_buf:
            slave_pkey_ts = self.server.slave_pkey_ts
            main_pubder = self.server.master_key.export_pubkey_der()
            identify = security.get_identify()

            self._notify_payload_buf = struct.pack(
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
        return self._notify_payload_buf + self.meta.device_status

    @property
    def _touch_payload(self):
        if not self._touch_payload_buf:
            temp_ts = self.server.slave_pkey_ts
            temp_pkey_der = self.server.slave_pkey.export_pubkey_der()
            temp_pkey_sign = self.server.master_key.sign(
                struct.pack("<f", temp_ts) + temp_pkey_der)

            self._touch_payload_buf = struct.pack(
                "<4sBB16sfHH",
                "FLUX",              # Magic String
                1,                   # Protocol Version
                3,                   # Tocuh Code
                UUID_BYTES,          # Device UUID
                temp_ts,
                len(temp_pkey_der),  # Temp pkey length
                len(temp_pkey_sign)  # Temp pkey sign
            ) + temp_pkey_der + temp_pkey_sign
        return self._touch_payload_buf

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
        Device Serial: device 16 (binary format). be 0 for broadcast.
        OP: Request code, looks for CODE_* consts
        """

        t1 = time()
        buf, endpoint = self.sock.recvfrom(4096)

        if len(buf) < 22:
            return  # drop if payload length too short

        magic_num, proto_ver, action_id, buuid = struct.unpack("<4sBB16s",
                                                               buf[:22])

        if magic_num != b"FLUX":
            logger.debug("Recive bad magic num: %s", magic_num)
            return

        if proto_ver == 0:
            return

        if proto_ver != self.PROTO_VER:
            logger.debug("Recive non support proto ver: %s", proto_ver)
            return

        if action_id == 0 and buuid == GLOBAL_SERIAL.bytes:
            self.send_notify_to(endpoint)

        elif buuid == UUID_BYTES:
            if action_id == 2:
                self.on_touch(endpoint)

            logger.debug("%s request 0x%x (t=%f)" % (
                endpoint[0], action_id, time() - t1))

    def send_response(self, endpoint, action_id, message):
        payload = struct.pack("<4sBB16sH", b"FLUX", 1, action_id + 1,
                              UUID_BYTES, len(message))
        signature = self.server.slave_pkey.sign(message)
        self.sock.sendto(payload + message + signature, endpoint)

    def close(self):
        self.sock.close()


class BroadcaseNotifyInterface(InterfaceBaseV1):
    _notify_payload_buf = None
    __last_notify = 0
    __period = None

    def __init__(self, server, config, sendto=("255.255.255.255", 1901)):
        super(BroadcaseNotifyInterface, self).__init__(server)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.endpoint = sendto
        self.__period = 2.5 if config == "A" else 27.5

    @property
    def _notify_payload(self):
        if not self._notify_payload_buf:
            self._notify_payload_buf = struct.pack(
                "<4sBB16s",
                "FLUX",             # Magic String
                0,                  # Protocol Version
                1,                  # Reserved
                UUID_BYTES)         # Device UUID
        return self._notify_payload_buf

    def send_notify(self):
        now = time()
        if now - self.__last_notify > self.__period:
            self.sock.sendto(self._notify_payload, self.endpoint)
            self.__last_notify = now

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
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.bind((ipaddr, port))


def create_interface_v2(cls):
    class InterfaceBaseV2Overlay(cls):
        PROTO_VER = 2

        @property
        def _notify_payload(self):
            if not self._notify_payload_buf:
                self._notify_payload_buf = struct.pack(
                    "<4sBB16s8s",
                    "FLUX",             # Magic String
                    2,                  # Protocol Version
                    0,                  # Discover Code
                    UUID_BYTES,         # Device UUID
                    os.urandom(8)
                )

            return self._notify_payload_buf + self.meta.device_status

        @property
        def _touch_payload(self):
            if not self._touch_payload_buf:
                pubkey_der = self.server.master_key.export_pubkey_der()
                identify = security.get_identify()
                self._touch_payload_buf = struct.pack(
                    "<4sBB16sHH",
                    "FLUX",              # Magic String
                    2,                   # Protocol Version
                    3,                   # Tocuh Code
                    UUID_BYTES,          # Device UUID
                    len(pubkey_der),     # Public Key length
                    len(identify),       # Identify length
                ) + pubkey_der + identify
            return self._touch_payload_buf

        def on_touch(self, endpoint):
            info = "serial=%s\x00ver=%s\x00model=%s\x00name=%s\x00pwd=%s" % (
                SERIAL_NUMBER, VERSION, MODEL_ID, self.meta.nickname,
                "T" if security.has_password() else "F",
            )

            payload = self._touch_payload + struct.pack("<H", len(info)) + info
            self.sock.sendto(payload, endpoint)
    return InterfaceBaseV2Overlay


class UpnpService(ServiceBase):
    bcst = None
    mcst = None
    ucst = None
    ucst_watcher = None
    cron_watcher = None
    ipaddress = None
    mversion = None

    def __init__(self, options):
        # Create RSA key if not exist. This will prevent upnp create key during
        # upnp is running (Its takes times and will cause timeout)
        self.master_key = security.get_private_key()
        self.slave_pkey = security.RSAObject(keylength=1024)

        self.meta = Metadata.instance()
        self.meta.shared_der_rsakey = self.slave_pkey.export_der()
        self.meta.update_device_status(0, 0, "OFFLINE", "")

        ServiceBase.__init__(self, logger, options)

        self.upnp_tcp = UpnpTcpInterface(self)

        self.nw_monitor = NetworkMonitor()
        self.nw_monitor_watcher = self.loop.io(self.nw_monitor, pyev.EV_READ,
                                               self.on_network_changed)
        self.nw_monitor_watcher.start()
        self.cron_watcher = self.loop.timer(3.0, 3.0, self.on_cron)
        self.cron_watcher.start()

    def get_last_ipaddr(self):
        status = self.nw_monitor.full_status()
        nested = [st.get('ipaddr', [])
                  for _, st in status.items()]
        ipaddress = list(chain(*nested))
        return ipaddress

    def on_network_changed(self, watcher, revent):
        if self.nw_monitor.read():
            if self.is_ipaddr_changed:
                ipaddress = self.get_last_ipaddr()

                if self.ipaddress != ipaddress:
                    logger.info("IP changed (%s -> %s)",
                                self.ipaddress, ipaddress)
                    self.ipaddress = ipaddress
                    self.teardown_upnp_sock()
                    self.setup_upnp_sock()

    def setup_upnp_sock(self):
        try:
            logger.info("Upnp going UP")

            storage = Storage("general", "meta")
            bare = storage["bare"] == "Y"
            bcst_config = storage["broadcast"]

            mcst_if =  create_interface_v2(MulticaseNotifyInterface)(self) if bare else MulticaseNotifyInterface(self)  # noqa
            mcst_watcher = self.loop.io(mcst_if, pyev.EV_READ,
                                        mcst_if.on_message)
            mcst_watcher.start()
            self.mcst = (mcst_if, mcst_watcher)

            ucst_if = create_interface_v2(UnicasetInterface)(self) if bare else UnicasetInterface(self)  # noqa
            ucst_watcher = self.loop.io(ucst_if, pyev.EV_READ,
                                        ucst_if.on_message)
            ucst_watcher.start()
            self.ucst = (ucst_if, ucst_watcher)

            if bcst_config != "N":
                bcst_if = create_interface_v2(BroadcaseNotifyInterface)(self, bcst_config) if bare else BroadcaseNotifyInterface(self, bcst_config)  # noqa
                bcst_watcher = self.loop.io(bcst_if, pyev.EV_READ,
                                            bcst_if.on_message)
                self.bcst = (bcst_if, bcst_watcher)

            self.mversion = self.meta.mversion
        except socket.error:
            logger.exception("Error while upnp going UP")
            self.teardown_upnp_sock()

    def teardown_upnp_sock(self):
        logger.info("Upnp going DOWN")
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
        self.slave_pkey_ts = time()  # TODO: for version 1 only
        self.ipaddress = self.get_last_ipaddr()
        self.mversion = self.meta.mversion
        self.setup_upnp_sock()

    def on_shutdown(self):
        self.teardown_upnp_sock()

    def on_cron(self, watcher, revent):
        if self.mversion != self.meta.mversion:
            logger.info("Metadata changed.")
            self.slave_pkey_ts = time()  # TODO: for version 1 only
            self.teardown_upnp_sock()
            self.setup_upnp_sock()

        if self.mcst:
            self.mcst[0].send_notify()
        if self.bcst:
            self.bcst[0].send_notify()
