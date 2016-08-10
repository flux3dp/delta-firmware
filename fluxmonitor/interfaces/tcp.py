
from binascii import b2a_hex as to_hex
from struct import Struct
import logging
import socket
import abc
import os

from fluxmonitor.err_codes import AUTH_ERROR
from fluxmonitor import security
from .base import InterfaceBase, HandlerBase, ConnectionClosedException

__all__ = ["TcpInterface", "TcpConnectionHandler"]
SHORT_PACKER = Struct("<H")
logger = logging.getLogger(__name__)


class TcpInterface(InterfaceBase):
    def create_socket(self, endpoint):
        logger.info("Listen on %s:%i", *endpoint)
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(endpoint)
        s.listen(2)
        return s

    @property
    def privatekey(self):
        try:
            return security.RSAObject(der=self.meta.shared_der_rsakey)
        except RuntimeError:
            logger.error("Slave key not ready, use master key instead")
            return security.get_private_key()


class TcpConnectionHandler(HandlerBase):
    send_watcher = None
    binary_mode = False
    delegate = None
    ready = False

    def __init__(self, kernel, sock, endpoint, pkey):
        self.logger = logger.getChild("%s:%s" % endpoint)
        self.logger.debug("Connected")
        super(TcpConnectionHandler, self).__init__(kernel, sock, endpoint)

        try:
            self.rsakey = pkey
            self.randbytes = security.randbytes(128)
            self._ipaddr = endpoint[0]
            self._buf = bytearray(4096)
            self._bufview = memoryview(self._buf)
            self._buffered = 0

            # Send handshake payload:
            #    "FLUX0002" (8 bytes)
            #    signed random bytes (private keysize)
            #    random bytes (128 bytes)
            buf = b"FLUX0002" + \
                  self.rsakey.sign(self.randbytes) + \
                  self.randbytes
            sock.send(buf)
        except Exception:
            # Ensure clean all resources
            self.close()
            raise

    @property
    def address(self):
        try:
            try:
                return socket.gethostbyaddr(self._ipaddr)[0]
            except Exception:
                return self._ipaddr
        except (OSError, socket.error):
            return "ZOMBIE"

    def on_recv(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._bufview[self._buffered:])
        except Exception:
            self.close("CONNECTION_GONE")

        if l:
            self._buffered += l
            if self.ready:
                self._on_message(l)
            else:
                self._on_handshake_identify(l)
        else:
            self.close("CONNECTION_GONE")

    def _on_handshake_identify(self, length):
        if self._buffered >= 20:
            access_id = to_hex(self._buf[:20])
            if access_id == "0" * 40:
                raise RuntimeError("Not implement")
            else:
                self.access_id = access_id
                self.logger.debug("Access ID: %s" % access_id)
                self.keyobj = security.get_keyobj(access_id=access_id)

                if self.keyobj:
                    if self._buffered >= (20 + self.keyobj.size()):
                        self._on_handshake_validate(length)
                else:
                    self._reply_handshake(AUTH_ERROR, success=False,
                                          log_message="Unknow Access ID")

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

            if not self.keyobj.verify(self.randbytes, signature):
                self._reply_handshake(AUTH_ERROR, success=False,
                                      log_message="Bad signature")

            else:
                self.randbytes = None
                self._reply_handshake(b"OK", True)

    def _reply_handshake(self, message, success, log_message=None):
        if len(message) < 16:
            message += b"\x00" * (16 - len(message))
        else:
            message = message[:16]

        if success:
            self.logger.info("Connected (access_id=%s)", self.access_id)
            self.sock.send(message)

            aes_key, aes_iv = os.urandom(32), os.urandom(16)
            self.aes = security.AESObject(aes_key, aes_iv)
            self.sock.send(self.keyobj.encrypt(aes_key + aes_iv))
            self._buffered = 0
            self._on_ready()
        else:
            self.logger.info("Handshake fail (%s)", log_message)
            self.sock.send(message)
            self.close()

    def _on_ready(self):
        self.ready = True
        self.on_ready()

    def _on_message(self, length):
        chunk = self._bufview[self._buffered - length:self._buffered]
        self.aes.decrypt_into(chunk, chunk)

        if self.binary_mode:
            ret = self._buffered
            self._buffered = 0
            self.delegate.on_binary(bytes(self._buf[:ret]), self)
        else:
            while self._buffered > 2:
                # Try unpack
                l = SHORT_PACKER.unpack_from(self._bufview[:2].tobytes())[0]
                if l > 4094:
                    self.close("Text payload too large, disconnect.")
                if self._buffered > l:
                    payload = self._bufview[2:l].tobytes()
                    self._bufview[:l - self._buffered] = \
                        self._bufview[l:self._buffered]
                    self._buffered -= l
                    self.delegate.on_text(payload.decode("utf8", "ignore"),
                                          self)
                elif self._buffered == l:
                    payload = self._bufview[2:l].tobytes()
                    self._buffered = 0
                    self.delegate.on_text(payload.decode("utf8", "ignore"),
                                          self)
                else:
                    break

    @abc.abstractmethod
    def on_ready(self):
        # on_ready should prepare and set self.deletage object which has
        # following methods:
        #     delegate.on_text(str, handler)
        #     delegate.on_binary(str, handler)
        #     delegate.on_close(handler)
        pass

    def send(self, buf):
        try:
            length = len(buf)
            buf = memoryview(self.aes.encrypt(buf))

            sent = self.sock.send(buf)
            while sent < length:
                sent += self.sock.send(buf[sent:])
            return length
        except socket.error as e:
            raise ConnectionClosedException("Socket error: %s" % e)

    def send_text(self, message):
        if isinstance(message, unicode):
            bmessage = message.encode("utf8")
        else:
            bmessage = message
        l = len(bmessage)
        buf = SHORT_PACKER.pack(l) + bmessage
        return self.send(buf)

    def async_send_binary(self, mimetype, length, stream, complete_cb):
        self.send_text("binary %s %i" % (mimetype, length))
        self.begin_send(stream, length, complete_cb)

    def close(self, message=None):
        if message:
            self.logger.info("Client disconnected (reason=%s)", message)
        if self.delegate:
            self.delegate.on_close(self)
            self.delegate = None
        super(TcpConnectionHandler, self).close()
