
import unittest
import msgpack
import struct
import socket
import pyev

from fluxmonitor.interfaces.usb2pc import USBProtocol


class USBProtocolImpl(USBProtocol):
    def __init__(self):
        self.loop = pyev.Loop()

        self.sock, self.sock2 = socket.socketpair()
        self.sock.setblocking(False)
        self.sock2.setblocking(False)
        self.watcher = self.loop.io(self.sock.fileno(), pyev.EV_READ,
                                    lambda *args: 0)
        self.initial_session()
        self.operations = []

    def open_channel(self, channel):
        self.operations.append(("open_channel", channel))

    def close_channel(self, channel):
        self.operations.append(("close_channel", channel))


class USBProtocolTest(unittest.TestCase):
    def setUp(self):
        self.usbprotocol = USBProtocolImpl()
        self.sock = self.usbprotocol.sock2

    def _recv_handshake(self):
        buf = b"\x00\x00"
        while buf == b"\x00\x00":
            buf = self.sock.recv(2)
        size = struct.unpack("<H", buf)[0]
        channel = ord(self.sock.recv(1))
        buf = self.sock.recv(size - 4)
        payload = msgpack.unpackb(buf)
        fin = ord(self.sock.recv(1))
        self.assertEqual(channel, 0xff)
        self.assertEqual(fin, 0xfe)
        return payload

    def _send_handshake(self, payload):
        rbuf = msgpack.packb({"session": payload["session"],
                              "client": "unittest"})
        self.sock.send(struct.pack("<HB", len(rbuf) + 4, 0xff))
        self.sock.send(rbuf)
        self.sock.send(b"\xfe")
        self.usbprotocol._on_recv(self.usbprotocol.watcher, 0)

    def _recv_handshake_ack(self):
        buf = self.sock.recv(2)
        size = struct.unpack("<H", buf)[0]
        channel = ord(self.sock.recv(1))
        buf = self.sock.recv(size - 4)
        fin = ord(self.sock.recv(1))
        self.assertEqual(channel, 0xfe)
        self.assertEqual(fin, 0xfe)

    def test_handshake(self):
        payload = self._recv_handshake()
        self._send_handshake(payload)
        self._recv_handshake_ack()
        self.assertEqual(self.usbprotocol._buffered, 0)

    def test_handshake_with_zero_prefix(self):
        self.sock.send(b"\x00" * 12)
        payload = self._recv_handshake()
        self._send_handshake(payload)
        self._recv_handshake_ack()

    def test_handshake_with_12345_to_16(self):
        payload = self._recv_handshake()
        self.sock.send("".join((chr(i) for i in range(1, 16))))
        self._send_handshake(payload)
        payload = self._recv_handshake()
        self._send_handshake(payload)
        self._recv_handshake_ack()
        self.assertEqual(self.usbprotocol._buffered, 0)

    def test_channel(self):
        self.usbprotocol._proto_handshake = True
        self.sock.recv(4096)

        # Send
        buf = msgpack.packb({"channel": 0, "action": "open"})
        self.sock.send(struct.pack("<HB", len(buf) + 4, 0xf0))
        self.sock.send(buf)
        self.sock.send(b"\xfe")
        self.usbprotocol._on_recv(self.usbprotocol.watcher, 0)

        # Recv
        buf = self.sock.recv(2)
        size = struct.unpack("<H", buf)[0]
        channel = ord(self.sock.recv(1))
        buf = self.sock.recv(size - 4)
        fin = ord(self.sock.recv(1))
        self.assertEqual(channel, 0xf0)
        self.assertEqual(fin, 0xfe)

        self.assertEqual([("open_channel", 0)],
                         self.usbprotocol.operations)
