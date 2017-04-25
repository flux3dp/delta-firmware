
# 1. Message:
#   Message length (<H), include this two bytes
#   Channel (<B)
#   Payload (any less then 1020 bytes)
#   FIN (<B) 0xf0=msgpack, 0xff=binary, 0xc0=binary ack = Device Side
#            0xb0=msgpack, 0xbf=binary, 0x80=binary ack = Client Size
#
# 2. Message:
#   Message length = (2 + 1 + payload + 1)
#
# 3. Channel
#   0xf0: reserved for channel management
#   0xf1: reserved for channel management
#   0xfa: reserved for client ping, fin is random
#   0xfb: reserved for client pong, fin must same as ping
#   0xfc: reserved for client request handshake, fin always 0xb0
#   0xfd: reserved for device complete handshake, fin always 0xf0
#   0xfe: reserved for client handshake ack, fin always 0xb0
#   0xff: reserved for handshake, fin always 0xf0
#
# 4. Handshake example
#   Device: 0xff, {session: int,  ...(DEVICE INFORMATION)}, 0xf0
#   Client: 0xfe, {session: int, ...(CLIENT INFOAMTION)}), 0xb0
#   Device: 0xfd, {session: int}), 0xf0
#
#   Client: 0xfc, None, 0xb0
#   Device: 0xff, {session: int,  ...(DEVICE INFORMATION)}, 0xf0
#
# 5. Channel example
#   Client: 0xf0, {"channel": 0, "action": "open"}, 0xb0
#   Device: 0xf1, {"channel": 0, "action": "open", "status": "ok"}, 0xf0
#
#   action: "open", "close"
#
# 6. Control example (Create channel 0x00 first)
#   Client: 0x00, ("REQUEST", PARAM0, PARAM1, ...)), 0xb0
#   Device: 0x00, ("ok", RET0, RET1, ...)), 0xf0
#
#   Client: 0x00, ("REQUEST", PARAM0, PARAM1, ...)), 0xb0
#   Device: 0x00, ("error", ("ERR_1", "ERR_2"), ...)), 0xf0
#
# 7. Binary example
#   Client: 0x00, ("upload", "binary/fcode", 12345)), 0xb0
#   Device: 0x00, ("continue", )), 0xf0
#   Client: 0x00, b"data1", 0xff
#   Device: 0x00, b"", 0x80  <======= ACK
#   Client: 0x00, b"data2", 0xff
#   Device: 0x00, b"", 0x80  <======= ACK
#   Device: 0x00, ("ok", RET0, RET1, ...)), 0xf0
#
#   Client: 0x00, ("download", "myfile/xxx.fc")), 0xb0
#   Device: 0x00, ("binary", "binary/fcode", 42342)), 0xf0
#   Device: 0x00, b"data1", 0xff
#   Client: 0x00, b"", 0x80  <======= ACK
#   Device: 0x00, b"data2", 0xff
#   Client: 0x00, b"", 0x80  <======= ACK
#   Device: 0x00, ("ok", )), 0xf0
#
# 8. Error case
#   When
#     a. message length > 1024 OR message length == 0
#     b. fin flag error (not in list)
#     c. payload can not unpack when fin flag=(0xf0, 0xb0)
#
#   Close all channel
#   Send 16 zero bytes
#   Back to waitting for handshake
#


from struct import Struct
import logging
import msgpack
import random


import pyev

from fluxmonitor.interfaces.handler import UnixHandler
from fluxmonitor.hal.misc import get_deviceinfo
from fluxmonitor.storage import metadata
from .usb_channels import CameraChannel, ConfigChannel, RobotChannel

global logger
logger = None
if __name__ != "__main__":
    logger = logging.getLogger(__name__)

HEAD_PACKER = Struct("<HB")
SHORT_PACKER = Struct("<H")
PAYLOAD_PACKER = Struct("<")
BUF_SIZE = 1024


class USBProtocol(object):
    _buf = None
    _buffered = 0
    _proto_handshake = False
    _proto_session = None
    _enable_padding = False

    def _on_recv(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._bufview[self._buffered:])
        except IOError as e:
            logger.debug("USB socket recv error %r", e)
            self.on_error()
            return

        try:
            self._buffered += l
            if l == 0:
                logger.debug("USB socket closed")
                self.on_error()
                return

            while self._buffered > 2:
                size = SHORT_PACKER.unpack_from(self._buf)[0]

                if size > BUF_SIZE:
                    if self._proto_handshake:
                        raise USBProtocolError("Message size overflow")
                    elif size == 0x0500:
                        self._bufview[0:self._buffered - 1] = \
                            self._bufview[1:self._buffered]
                        self._buffered -= 1
                        continue
                    else:
                        logger.debug(
                            "Recv bad handshake, clean buffer"
                            " (payload size=%i, %r)", size,
                            self._buf[:self._buffered])
                        self._buffered = 0
                elif size == 0:
                    if self._proto_handshake:
                        raise USBProtocolError("Got zero size payload")
                    else:
                        if self._buffered > 2:
                            self._bufview[:self._buffered - 2] = \
                                self._bufview[2:self._buffered]
                            self._buffered -= 2
                        else:
                            self._buffered = 0
                        continue
                elif size > self._buffered:
                    return

                chl_idx = self._buf[2]
                buf = self._bufview[3:size - 1]
                fin = self._buf[size - 1]

                if self._proto_handshake:
                    self._on_message(chl_idx, buf, fin)
                else:
                    self._on_handshake(chl_idx, buf, fin)

                if self._buffered > size:
                    self._bufview[:self._buffered - size] = \
                        self._bufview[size:self._buffered]
                    self._buffered -= size
                else:
                    self._buffered = 0
        except USBProtocolError as e:
            logger.warning("Reset connection (protocol error: %s)", e)
            self.initial_session()
        except Exception:
            logger.exception("Unhandle error")
            self.initial_session()

    def _on_handshake(self, chl_idx, buf, fin):
        logger.debug("on_handshake channel=0x%02x, fin=0x%02x", chl_idx, fin)

        if chl_idx == 0xa0 and fin == 0xff:
            pass
        elif chl_idx == 0xfa:
            logger.debug("Recv ping but not handshaked")
            pass
        elif fin != 0xb0:
            logger.debug("Fin error (0x%02x!=0xb0) in handshake", fin)
            pass
        elif chl_idx == 0xfe:
            data = msgpack.unpackb(buf.tobytes())
            if data.get("session") == self._proto_session:
                self.client_profile = data
                logger.debug("Client handshake complete: %s", data)

                response = {"session": self._proto_session}

                if data.get("protocol_level") >= 1:
                    self._enable_padding = True
                    response["protocol_level"] = 1
                    logger.debug("Apply protocol level 1")

                self.send_payload(0xfd, response)
                self._proto_handshake = True
                self.on_handshake_complete()
            else:
                logger.debug("Handshake session error")
        elif chl_idx == 0xfc:
            logger.debug("Resend handshake")
            self.send_handshake()
        else:
            logger.debug("Channel error (0x%02x!=0xff) in handshake", chl_idx)

    def _on_message(self, chl_idx, buf, fin):
        if chl_idx < 0x80:
            if fin == 0xb0:
                self.on_payload(chl_idx, msgpack.unpackb(buf.tobytes()))
            elif fin == 0xbf:
                self.on_binary(chl_idx, buf)
            elif fin == 0x80:
                self.on_binary_ack(chl_idx)
            else:
                raise USBProtocolError("Bad fin 0x%x" % fin)
        elif chl_idx == 0xa0 and fin == 0xff:
            pass
        elif chl_idx == 0xf0:
            if fin != 0xb0:
                raise USBProtocolError("Bad fin for channel 0xf0")
            data = msgpack.unpackb(buf.tobytes())
            self._control_channel(data.get("channel"), data.get("action"),
                                  data.get("type", "robot"))
        elif chl_idx == 0xfa:
            self._handle_ping(fin)
        elif chl_idx == 0xfc:
            raise USBProtocolError("Recv channel 0xfc, reset session")
        else:
            raise USBProtocolError("Bad channel 0x%x" % chl_idx)

    def _control_channel(self, chl_idx, action, tp=None):
        logger.debug("Channel operation: index=%i, action=%s", chl_idx, action)
        st = None
        if chl_idx >= 0 and chl_idx < 0x80:
            if action == "open":
                st = self.open_channel(chl_idx, tp)
            elif action == "close":
                st = self.close_channel(chl_idx)
        else:
            st = "error"
        self.send_payload(0xf1, {"channel": chl_idx, "action": action,
                                 "status": st})

    def _handle_ping(self, fin):
        data = metadata.device_status
        buf = HEAD_PACKER.pack(len(data) + 4, 0xfb) + data + b"\x00"
        self.sock.send(buf)

    def initial_session(self):
        self.watcher.stop()
        self.watcher.callback = self._on_recv
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.start()

        if self._buffered:
            logger.debug("Connection reset...")
            logger.debug("Data left in buffer: %r", self._buf[:self._buffered])

        logger.debug("==== INITIAL SESSION ====")
        self._proto_handshake = False
        self.sock.send(b"\x00" * 16)
        if self._buf is None:
            self._buf = bytearray(BUF_SIZE)
            self._bufview = memoryview(self._buf)
        self._buffered = 0

        session = random.randint(0, 65536)
        if self._proto_session == session:
            self._proto_session = (session + 1) % 65536
        else:
            self._proto_session = session

        self.send_handshake()

    def send_handshake(self):
        handshake_data = get_deviceinfo(metadata)
        handshake_data["session"] = self._proto_session
        logger.debug("Send handshake")
        self.send_payload(0xff, handshake_data)

    def on_handshake_complete(self):
        pass

    def on_payload(self, chl_idx, payload):
        pass

    def on_binary(self, chl_idx, buf):
        pass

    def on_binary_ack(self, chl_idx):
        pass

    def _send(self, buf):
        size = len(buf)
        sent = 0
        while sent < size:
            sent += self.sock.send(buf[sent:])

    def send_payload(self, chl_idx, obj):
        data = msgpack.packb(obj)
        l = len(data) + 4
        if l < 508 and self._enable_padding and self._proto_handshake:
            padding = 512 - l
            buf = b"".join((
                HEAD_PACKER.pack(l, chl_idx), data, b"\xf0",
                HEAD_PACKER.pack(padding, 0xa0), b"\x00" * (padding - 4), b"\xff"))  # noqa
        else:
            buf = b"".join((HEAD_PACKER.pack(l, chl_idx), data, b"\xf0"))

        self._send(buf)

    def send_binary(self, chl_idx, data):
        l = len(data) + 4
        if l < 508 and self._enable_padding and self._proto_handshake:
            padding = 512 - l
            buf = b"".join((
                HEAD_PACKER.pack(l, chl_idx), data, b"\xff",
                HEAD_PACKER.pack(padding, 0xa0), b"\x00" * (padding - 4), b"\xff"))  # noqa
        else:
            buf = b"".join((HEAD_PACKER.pack(l, chl_idx), data, b"\xff"))
        self._send(buf)

    def send_binary_ack(self, chl_idx):
        buf = HEAD_PACKER.pack(4, chl_idx) + b"\xc0"
        self.sock.send(buf)


class USBChannelProtocol(USBProtocol):
    channels = []
    stack = None

    def initial_session(self):
        super(USBChannelProtocol, self).initial_session()

        for c in self.channels:
            c.close()
        self.channels = [null_channel for i in xrange(8)]

    def open_channel(self, channel_idx, channel_type):
        if channel_idx >= 8:
            logger.debug("Can not create channel at index %i", channel_idx)
            return "BAD_PARAMS"
        if self.channels[channel_idx]:
            logger.debug("Channel %i is already opened", channel_idx)
            return "RESOURCE_BUSY"

        try:
            if channel_type == "camera":
                c = CameraChannel(channel_idx, self)
            elif channel_type == "config":
                c = ConfigChannel(channel_idx, self)
            else:
                c = RobotChannel(channel_idx, self)
        except IOError:
            return "SUBSYSTEM_ERROR"

        self.channels[channel_idx] = c
        logger.debug("Channel %s opened", c)
        return "ok"

    def get_channel(self, channel_idx):
        return self.channels[channel_idx]

    def close_channel(self, channel_idx):
        if channel_idx >= 8:
            logger.debug("Can not close channel at index %i", channel_idx)
            return "BAD_PARAMS"
        if not self.channels[channel_idx]:
            logger.debug("Channel %i is not opened", channel_idx)
            return "RESOURCE_BUSY"

        c = self.channels[channel_idx]
        self.channels[channel_idx] = null_channel
        c.close()
        logger.debug("Channel %s closed", c)
        return "ok"

    def on_payload(self, channel_idx, payload):
        self.channels[channel_idx].on_payload(payload)

    def on_binary(self, channel_idx, buf):
        self.send_binary_ack(channel_idx)
        self.channels[channel_idx].on_binary(buf)

    def on_binary_ack(self, channel_idx):
        self.channels[channel_idx].on_binary_ack()


class USBHandler(USBChannelProtocol, UnixHandler):
    usbcabel = None

    def on_connected(self):
        super(USBHandler, self).on_connected()
        self.initial_session()


class NullChannel(object):
    def __nonzero__(self):
        return False

    def on_payload(self, o):
        logger.debug("null channel recv payload")

    def on_binary(self, b):
        logger.debug("null channel recv binary")

    def on_binary_ack(self):
        logger.debug("null channel recv binary ack")

    def close(self):
        pass


null_channel = NullChannel()


class USBProtocolError(Exception):
    pass
