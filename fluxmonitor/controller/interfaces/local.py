
from binascii import b2a_hex as to_hex
from weakref import WeakSet
import logging
import struct
import socket
import os

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.misc import timer as T
from fluxmonitor import security

logger = logging.getLogger(__name__)
PRIVATE_KEY = security.get_private_key()
IDLE_TIMEOUT = 3600.  # Close conn if idel after seconds.


class LocalControl(object):
    def __init__(self, server, logger=None, port=23811):
        self.server = server
        self.logger = logger.getChild("lc") if logger \
            else logging.getLogger(__name__)

        self.serve_sock = s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))

        serve_sock_io = AsyncIO(s, self.on_accept)

        self.server.add_read_event(serve_sock_io)
        self.io_list = WeakSet()
        self.io_list = [serve_sock_io]
        self.logger.info("Listen on %s:%i" % ("", port))

        s.listen(1)

    def on_accept(self, sender):
        endpoint = sender.obj.accept()
        LocalConnectionAsyncIO(endpoint, self.server, self.logger)

    def close(self):
        while self.io_list:
            io = self.io_list.pop()
            self.server.remove_read_event(io)
            # TODO: Close socket


class LocalConnectionAsyncIO(object):
    @T.update_time
    def __init__(self, endpoint, server, logger):
        self.binary_mode = False

        self.sock, self.client = endpoint
        self.server = server
        self.logger = logger.getChild("%s:%s" % self.client)

        self.randbytes = security.randbytes(128)

        self._buf = bytearray(4096)
        self._bufview = memoryview(self._buf)
        self._buffered = 0

        """
        Send handshake payload:
            "FLUX0002" (8 bytes)
            signed random bytes (private keysize)
            random bytes (128 bytes)
        """
        buf = b"FLUX0002" + \
              PRIVATE_KEY.sign(self.randbytes) + \
              self.randbytes
        self.sock.send(buf)

        self._recv_handler = self._on_handshake_identify

        server.add_read_event(self)
        server.add_loop_event(self)

    def fileno(self):
        return self.sock.fileno()

    @T.update_time
    def on_read(self, sender):
        l = self.sock.recv_into(self._bufview[self._buffered:])
        if l:
            self._buffered += l
            self._recv_handler(sender, l)
        else:
            self.close("Remote closed")

    def on_write(self, sender):
        pass

    def on_loop(self, sender):
        if T.time_since_update(self) > IDLE_TIMEOUT:
            self.close("Idle timeout")

    def _on_handshake_identify(self, sender, length):
        if self._buffered >= 20:
            access_id = to_hex(self._buf[:20])
            if access_id == "0" * 40:
                raise RuntimeError("Not implement")
            else:
                self.access_id = access_id
                self.logger.debug("Access ID: %s" % access_id)
                self.keyobj = security.get_keyobj(access_id=access_id)

                if self._buffered >= (20 + self.keyobj.size()):
                    self._on_handshake_validate(sender, length)
                else:
                    self._recv_handler = self._on_handshake_identify

    def _on_handshake_validate(self, sender, length):
        """
        Recive handshake payload:
            access id (20 bytes)
            signature (remote private key size)

        Send final handshake payload:
            message (16 bytes)
        """
        req_hanshake_len = 20 + self.keyobj.size()

        if self._buffered > req_hanshake_len:
            self._reply_handshake(sender, b"PROTOCOL_ERROR", success=False,
                                  log_message="Handshake message too long")

        elif self._buffered == req_hanshake_len:
            signature = self._buf[20:req_hanshake_len]

            if not self.keyobj:
                self._reply_handshake(sender, b"AUTH_FAILED", success=False,
                                      log_message="Unknow Access ID")

            elif not self.keyobj.verify(self.randbytes, signature):
                self._reply_handshake(sender, b"AUTH_FAILED", success=False,
                                      log_message="Bad signature")

            else:
                self.randbytes = None
                self.sock.send(b"OK" + b"\x00" * 14)
                self.logger.info("Client %s connected (access_id=%s)" %
                                 (self.client[0], self.access_id))

                aes_key, aes_iv = os.urandom(32), os.urandom(16)
                self.aes = security.AESObject(aes_key, aes_iv)
                self.sock.send(self.keyobj.encrypt(aes_key + aes_iv))

                self._buffered = 0
                self._recv_handler = self._on_message

    def _on_message(self, sender, length):
        chunk = self._bufview[self._buffered - length:self._buffered]
        self.aes.decrypt_into(chunk, chunk)

        if self.binary_mode:
            ret = self._buffered
            self._buffered = 0
            sender.on_message(bytes(self._buf[:ret]), self)
        else:
            while self._buffered > 2:
                # Try unpack
                l = struct.unpack_from("<H", self._bufview[:2].tobytes())[0]
                if l > 4094:
                    self.close("Text payload too large, disconnect.")
                if self._buffered > l:
                    payload = self._bufview[2:l].tobytes()
                    self._bufview[:l - self._buffered] = \
                        self._bufview[l:self._buffered]
                    self._buffered -= l
                    sender.on_message(payload, self)
                elif self._buffered == l:
                    payload = self._bufview[2:l].tobytes()
                    self._buffered = 0
                    sender.on_message(payload, self)
                else:
                    break

    def _reply_handshake(self, sender, message, success, log_message=None):
        if len(message) < 16:
            message += b"\x00" * (16 - len(message))
        else:
            message = message[:16]

        if success:
            self.logger.info(log_message)
            self.sock.send(message)
        else:
            self.logger.error(log_message)
            self.sock.send(message)
            self.close()

    def send(self, buf):
        length = len(buf)
        buf = memoryview(self.aes.encrypt(buf))

        sent = self.sock.send(buf)
        while sent < length:
            sent += self.sock.send(buf[sent:])
        return length

    def send_text(self, message):
        l = len(message)
        buf = struct.pack("<H", l) + message.encode()
        return self.send(buf)

    def close(self, reason=""):
        self._recv_handler = None
        self.server.remove_read_event(self)
        self.server.remove_loop_event(self)
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
        self.logger.debug("Client %s disconnected (reason=%s)" %
                          (self.client[0], reason))
