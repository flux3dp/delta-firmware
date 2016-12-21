
# 1. Message:
#   Message length (<H), include this two bytes
#   Channel (<B)
#   Payload (any less then 1020 bytes)
#   FIN (<B) (0xfe=msgpack, 0xff=binary, 0x80=binary ack)
#
# 2. Message:
#   Message length = (2 + 1 + payload + 1)
#
# 3. Channel
#   0xf0: reserved for channel management
#   0xfd: reserved for client request handshake, fin always 0xfe
#   0xfe: reserved for handshake ack, fin always 0xfe
#   0xff: reserved for handshake, fin always 0xfe
#
# 4. Handshake example
#   Device: 0xff, {session: int,  ...(DEVICE INFORMATION)}, 0xfe
#   Client: 0xff, {session: int, ...(CLIENT INFOAMTION)}), 0xfe
#   Device: 0xfe, {session: int}), 0xfe
#
#   Client: 0xfd, None, 0xfe
#   Device: 0xff, {session: int,  ...(DEVICE INFORMATION)}, 0xfe
#
# 5. Channel example
#   Client: 0xf0, {"channel": 0, "action": "open"}, 0xfe
#   Device: 0xf0, {"channel": 0, "action": "open", "status": "ok"}, 0xfe
#
#   action: "open", "close"
#
# 6. Control example (Create channel 0x00 first)
#   Client: 0x00, ("REQUEST", PARAM0, PARAM1, ...)), 0xfe
#   Device: 0x00, ("ok", RET0, RET1, ...)), 0xfe
#
#   Client: 0x00, ("REQUEST", PARAM0, PARAM1, ...)), 0xfe
#   Device: 0x00, ("error", ("ERR_1", "ERR_2"), ...)), 0xfe
#
# 7. Binary example
#   Client: 0x00, ("upload", "binary/fcode", 12345)), 0xfe
#   Device: 0x00, ("continue", )), 0xfe
#   Client: 0x00, b"data1", 0xff
#   Device: 0x00, b"", 0x80  <======= ACK
#   Client: 0x00, b"data2", 0xff
#   Device: 0x00, b"", 0x80  <======= ACK
#   Device: 0x00, ("ok", RET0, RET1, ...)), 0xfe
#
#   Client: 0x00, ("download", "myfile/xxx.fc")), 0xfe
#   Device: 0x00, ("binary", "binary/fcode", 42342)), 0xfe
#   Device: 0x00, b"data1", 0xff
#   Client: 0x00, b"", 0x80  <======= ACK
#   Device: 0x00, b"data2", 0xff
#   Client: 0x00, b"", 0x80  <======= ACK
#   Device: 0x00, ("ok", )), 0xfe
#
# 8. Error case
#   When
#     a. message length > 1024 OR message length == 0
#     b. fin flag error (not 0x80, 0xfe, 0xff)
#     c. payload can not unpack when fin flag=0xfe
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
from fluxmonitor.interfaces.robot import ServiceStack
from fluxmonitor.hal.misc import get_deviceinfo
from fluxmonitor.storage import Metadata

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

        if fin != 0xfe:
            logger.debug("Fin error (0x%02x!=0xfe) in handshake", fin)
            return

        if chl_idx == 0xff:
            data = msgpack.unpackb(buf.tobytes())
            if data.get("session") == self._proto_session:
                self.client_profile = data
                logger.debug("Client handshake complete: %s", data)

                self.send_payload(0xfe, {"session": self._proto_session})
                self._proto_handshake = True
                self.on_handshake_complete()
            else:
                logger.debug("Handshake session error")
        elif chl_idx == 0xfd:
            logger.debug("Resend handshake")
            self.send_handshake()
        else:
            logger.debug("Channel error (0x%02x!=0xff) in handshake", chl_idx)

    def _on_message(self, chl_idx, buf, fin):
        if chl_idx < 0x80:
            if fin == 0xfe:
                self.on_payload(chl_idx, msgpack.unpackb(buf.tobytes()))
            elif fin == 0xff:
                self.on_binary(chl_idx, buf)
            elif fin == 0x80:
                self._feed_binary(self.watcher)
            else:
                raise USBProtocolError("Bad fin 0x%x" % fin)
        elif chl_idx == 0xf0:
            if fin != 0xfe:
                raise USBProtocolError("Bad fin for channel 0xf0")
            data = msgpack.unpackb(buf.tobytes())
            self._control_channel(data.get("channel"), data.get("action"))
        else:
            raise USBProtocolError("Bad channel 0x%x" % chl_idx)

    def _control_channel(self, chl_idx, action):
        st = None
        if chl_idx >= 0 and chl_idx < 128:
            if action == "open":
                st = "ok" if self.open_channel(chl_idx) else "error"
            elif action == "close":
                st = "ok" if self.close_channel(chl_idx) else "error"
        else:
            st = "error"
        self.send_payload(0xf0, {"channel": chl_idx, "action": action,
                                 "status": st})

    def _feed_binary(self, watcher, revent=None):
        try:
            chl_idx, length, sent_length, stream, callback = watcher.data

            if length == sent_length:
                logger.debug("Binary sent")
                watcher.data = None
                callback(self)
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

    def send_payload(self, chl_idx, obj):
        payload = msgpack.packb(obj)
        buf = HEAD_PACKER.pack(len(payload) + 4, chl_idx) + payload + b"\xfe"
        self.sock.send(buf)

    def send_binary_ack(self, chl_idx):
        buf = HEAD_PACKER.pack(4, chl_idx) + b"\x80"
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


class USBRobotProtocol(USBProtocol):
    channels = []
    stack = None

    def initial_session(self):
        super(USBRobotProtocol, self).initial_session()

        for c in self.channels:
            if c:
                c.close()
        self.channels = [None, None, None, None]

    def open_channel(self, channel_idx):
        if channel_idx > 4:
            return False
        if self.channels[channel_idx]:
            return False
        self.channels[channel_idx] = Channel(channel_idx, self)
        return True

    def close_channel(self, channel_idx):
        if channel_idx > 4:
            return False
        if self.channels[channel_idx] is None:
            return False
        self.channels[channel_idx].close()
        self.channels[channel_idx] = None
        return True

    def on_payload(self, channel_idx, payload):
        self.channels[channel_idx].on_payload(payload)

    def on_binary(self, channel_idx, buf):
        self.send_binary_ack(channel_idx)
        self.channels[channel_idx].on_binary(buf)


class Channel(object):
    def __init__(self, index, protocol):
        self.index = index
        self.protocol = protocol
        self.stack = ServiceStack(self.protocol.kernel)

    @property
    def address(self):
        return "USB#%i" % (self.index)

    def send_text(self, string):
        self.protocol.send_payload(self.index, (string, ))

    def async_send_binary(self, mimetype, length, stream, cb):
        self.protocol.send_payload(self.index,
                                   "binary %s %i" % (mimetype, length))
        self.protocol.begin_send(self.index, stream, length, cb)

    def on_payload(self, obj):
        self.stack.on_text(" ".join("%s" % i for i in obj), self)

    def on_binary(self, buf):
        self.stack.on_binary(buf, self)

    def close(self):
        self.stack.on_close(self)
        self.stack = None


class USBHandler(USBRobotProtocol, UnixHandler):
    usbcabel = None

    def on_connected(self):
        super(USBHandler, self).on_connected()
        self.initial_session()


class USBProtocolError(Exception):
    pass
