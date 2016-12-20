
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
from fluxmonitor.storage import Metadata
from .usb_channels import CameraChannel, ConfigChannel, RobotChannel

global logger
logger = None
if __name__ != "__main__":
    logger = logging.getLogger(__name__)

HEAD_PACKER = Struct("<HB")
SHORT_PACKER = Struct("<H")
BUF_SIZE = 1024


class USBProtocol(object):
    _buf = None
    _proto_handshake = False
    _proto_session = None

    def _on_recv(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._bufview[self._buffered:])
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
            return

        try:
            self._buffered += l
            if l == 0:
                self.on_error()
                return

            while self._buffered > 2:
                size = SHORT_PACKER.unpack_from(self._buf)[0]

                if size > BUF_SIZE:
                    if self._proto_handshake:
                        raise USBProtocolError("Message size overflow")
                    else:
                        logger.debug("Recv bad handshake, clean buffer")
                        self._buffered = 0
                if size == 0:
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
                if size > self._buffered:
                    return

                chl_idx = self._buf[2]
                buf = self._bufview[3:size - 1]
                fin = self._buf[size - 1]

                if self._proto_handshake:
                    self._on_message(chl_idx, buf, fin)
                else:
                    self._on_handshake(chl_idx, buf, fin)

                if size > self._buffered:
                    self._bufview[:self._buffered - size] = \
                        self._bufview[size:self._buffered]
                    self._buffered -= size
                else:
                    self._buffered = 0
        except USBProtocolError as e:
            logger.error("Protocol error: %s", e)
            self.initial_session()
        except Exception:
            logger.exception("Unhandle error")
            self.initial_session()

    def _on_handshake(self, chl_idx, buf, fin):
        logger.debug("on_handshake channel=0x%02x, fin=0x%02x", chl_idx, fin)

        if chl_idx == 0xfa:
            logger.debug("Recv ping but not handshaked")
            self.send_handshake()
            return

        if fin != 0xb0:
            logger.debug("Fin error (0x%02x!=0xb0) in handshake", fin)
            return

        if chl_idx == 0xfe:
            data = msgpack.unpackb(buf.tobytes())
            if data.get("session") == self._proto_session:
                self.client_profile = data
                logger.debug("Client handshake complete: %s", data)

                self.send_payload(0xfd, {"session": self._proto_session})
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
                if self.watcher.data:
                    self._feed_binary(self.watcher)
                else:
                    self.on_binary_ack(chl_idx)
            else:
                raise USBProtocolError("Bad fin 0x%x" % fin)
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
        self.send_payload(0xfb, None, fin)

    def _feed_binary(self, watcher, revent=None):
        try:
            chl_idx, length, sent_length, stream, callback = watcher.data

            if length == sent_length:
                logger.debug("Binary sent")
                watcher.data = None
                callback(self.get_channel(chl_idx))
                return

            bdata = stream.read(min(length - sent_length, 1020))
            buf = HEAD_PACKER.pack(len(bdata) + 4, chl_idx) + bdata + b"\xff"
            l = self.sock.send(buf)
            if l != len(buf):
                logger.error("Socket %s send data failed", self)
                self.on_error()
                return

            sent_length += len(bdata)

            if sent_length > length:
                logger.error("GG on socket %s", self.sock)
                self.on_error()

            else:
                watcher.data = (chl_idx, length, sent_length, stream, callback)

        except IOError as e:
            logger.debug("Send error: %s", e)
            watcher.stop()
            self.on_error()
        except Exception:
            logger.exception("Unknow error")
            watcher.stop()
            self.on_error()

    def initial_session(self):
        self.watcher.stop()
        self.watcher.data = None
        self.watcher.callback = self._on_recv
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.start()

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
        handshake_data = get_deviceinfo(Metadata())
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

    def send_payload(self, chl_idx, obj):
        payload = msgpack.packb(obj)
        buf = HEAD_PACKER.pack(len(payload) + 4, chl_idx) + payload + b"\xf0"
        self.sock.send(buf)

    def send_binary(self, chl_idx, data):
        buf = HEAD_PACKER.pack(len(data) + 4, chl_idx) + data + b"\xff"
        self.sock.send(buf)

    def send_binary_ack(self, chl_idx):
        buf = HEAD_PACKER.pack(4, chl_idx) + b"\xc0"
        self.sock.send(buf)

    def begin_send(self, chl_idx, stream, length, complete_callback):
        if self.watcher.data:
            raise RuntimeError("RESOURCE_BUSY")

        if length > 0:
            data = (chl_idx, length, 0, stream, complete_callback)
            self.watcher.data = data
            self._feed_binary(self.watcher)
        else:
            complete_callback(self)


class USBChannelProtocol(USBProtocol):
    channels = []
    stack = None

    def initial_session(self):
        super(USBChannelProtocol, self).initial_session()

        for c in self.channels:
            if c:
                c.close()
        self.channels = [None for i in xrange(8)]

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
        if self.channels[channel_idx] is None:
            logger.debug("Channel %i is not opened", channel_idx)
            return "RESOURCE_BUSY"

        c = self.channels[channel_idx]
        self.channels[channel_idx] = None
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


class USBProtocolError(Exception):
    pass
