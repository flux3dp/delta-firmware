
from binascii import b2a_hex as to_hex
import weakref
import logging
import struct
import socket
import os

import pyev

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.misc import timer as T
from fluxmonitor import security

logger = logging.getLogger(__name__)
IDLE_TIMEOUT = 3600.  # Close conn if idel after seconds.


class LocalControl(object):
    def __init__(self, kernel, logger=None, port=23811):
        self.kernel = kernel
        self.logger = logger.getChild("lc") if logger \
            else logging.getLogger(__name__)
        self.meta = CommonMetadata()

        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))

        self.listen_watcher = kernel.loop.io(s, pyev.EV_READ, self.on_accept,
                                             s)
        self.listen_watcher.start()
        self.timer_watcher = kernel.loop.timer(30, 30, self.on_timer)

        self.io_list = []
        self.logger.info("Listen on %s:%i" % ("", port))

        s.listen(1)

    def on_accept(self, watcher, revent):
        try:
            sock, endpoint = watcher.data.accept()
            sublogger = logger.getChild("%s:%s" % endpoint)

            try:
                der = self.meta.shared_der_rsakey
                key = security.RSAObject(der=der)
                h = LocalConnectionHandler(sock, key, sublogger,
                                           self.kernel.on_message)
            except RuntimeError:
                logger.error("Slave key not ready, use master key instead")
                h = LocalConnectionHandler(sock, security.get_private_key(),
                                           sublogger, self.kernel.on_message)

            io_watcher = watcher.loop.io(sock, pyev.EV_READ, self.on_read, h)
            io_watcher.start()
            self.io_list.append(io_watcher)
        except Exception:
            logger.exception("Unhandle Error")

    def on_read(self, watcher, revent):
        try:
            if not watcher.data.on_read():
                watcher.data.close("Remote gone")
                watcher.stop()
                self.io_list.remove(watcher)
        except Exception:
            logger.exception("Unhandle Error")

    def on_timer(self, watcher, revent):
        dead = []
        for w in self.io_list:
            if w.data.is_timeout:
                dead.append(w)

        for w in dead:
            w.data.close("Idle timeout")
            watcher.stop()
            self.io_list.remove(watcher)

    def close(self):
        self.timer_watcher.stop()
        self.timer_watcher = None
        self.listen_watcher.stop()
        self.listen_watcher = None

        while self.io_list:
            watcher = self.io_list.pop()
            watcher.data.close()
            watcher.stop()


class LocalConnectionHandler(object):
    @T.update_time
    def __init__(self, sock, slave_key, logger, on_message_callback):
        self.binary_mode = False

        self._on_message_callback = on_message_callback
        self.rsakey = slave_key
        self.logger = logger

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
              self.rsakey.sign(self.randbytes) + \
              self.randbytes
        sock.send(buf)

        self.sock = sock
        self._recv_handler = self._on_handshake_identify

    @property
    def is_timeout(self):
        return T.time_since_update(self) > IDLE_TIMEOUT

    @T.update_time
    def on_read(self):
        l = self.sock.recv_into(self._bufview[self._buffered:])
        if l:
            self._buffered += l
            self._recv_handler(l)
            return True
        else:
            return False
            self.close("Remote closed")

    @T.update_time
    def on_write(self):
        pass

    def _on_handshake_identify(self, length):
        if self._buffered >= 20:
            access_id = to_hex(self._buf[:20])
            if access_id == "0" * 40:
                raise RuntimeError("Not implement")
            else:
                self.access_id = access_id
                self.logger.debug("Access ID: %s" % access_id)
                self.keyobj = security.get_keyobj(access_id=access_id)

                if self._buffered >= (20 + self.keyobj.size()):
                    self._on_handshake_validate(length)
                else:
                    self._recv_handler = self._on_handshake_identify

    def _on_handshake_validate(self, length):
        """
        Recive handshake payload:
            access id (20 bytes)
            signature (remote private key size)

        Send final handshake payload:
            message (16 bytes)
        """
        req_hanshake_len = 20 + self.keyobj.size()

        if self._buffered > req_hanshake_len:
            self._reply_handshake(b"PROTOCOL_ERROR", success=False,
                                  log_message="Handshake message too long")

        elif self._buffered == req_hanshake_len:
            signature = self._buf[20:req_hanshake_len]

            if not self.keyobj:
                self._reply_handshake(b"AUTH_FAILED", success=False,
                                      log_message="Unknow Access ID")

            elif not self.keyobj.verify(self.randbytes, signature):
                self._reply_handshake(b"AUTH_FAILED", success=False,
                                      log_message="Bad signature")

            else:
                self.randbytes = None
                self.sock.send(b"OK" + b"\x00" * 14)
                self.logger.info("Connected (access_id=%s)", self.access_id)

                aes_key, aes_iv = os.urandom(32), os.urandom(16)
                self.aes = security.AESObject(aes_key, aes_iv)
                self.sock.send(self.keyobj.encrypt(aes_key + aes_iv))

                self._buffered = 0
                self._recv_handler = self._on_message

    def _on_message(self, length):
        chunk = self._bufview[self._buffered - length:self._buffered]
        self.aes.decrypt_into(chunk, chunk)

        if self.binary_mode:
            ret = self._buffered
            self._buffered = 0
            self._on_message_callback(bytes(self._buf[:ret]), self)
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
                    self._on_message_callback(payload, self)
                elif self._buffered == l:
                    payload = self._bufview[2:l].tobytes()
                    self._buffered = 0
                    self._on_message_callback(payload, self)
                else:
                    break

    def _reply_handshake(self, message, success, log_message=None):
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
        if isinstance(message, unicode):
            bmessage = message.encode("utf8")
        else:
            bmessage = message
        l = len(bmessage)
        buf = struct.pack("<H", l) + bmessage
        return self.send(buf)

    def send_large_data(self, binary):
        pass

    def close(self, reason=""):
        self._recv_handler = None
        self.sock.close()
        self.logger.debug("Client disconnected (reason=%s)", reason)
