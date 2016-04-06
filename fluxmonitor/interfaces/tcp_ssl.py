
from binascii import b2a_hex as to_hex, a2b_hex as from_hex
from OpenSSL import crypto
from struct import Struct
import logging
import socket
import abc
import ssl

import pyev

from fluxmonitor.security import (is_trusted_remote, get_uuid, get_keyobj,
                                  randbytes, hash_password)
from fluxmonitor.storage import Storage
from .base import InterfaceBase, HandlerBase

MESSAGE_OK = b"OK              "
MESSAGE_AUTH_ERROR = b"AUTH_ERROR      "
MESSAGE_UNKNOWN_HOST = b"UNKNOWN_HOST    "
MESSAGE_PROTOCOL_ERROR = b"PROTOCOL_ERROR  "
SHORT_PACKER = Struct("<H")
UUID_HEX = get_uuid()
UUID_BIN = from_hex(UUID_HEX)
__all__ = ["SSLInterface", "SSLConnectionHandler"]
logger = logging.getLogger(__name__)


def prepare_cert():
    from fluxmonitor.security import (get_private_key, get_serial,
                                      get_identify)

    s = Storage("security", "private")
    pkey = get_private_key()
    if not s.exists("sslkey.pem"):
        s["sslkey.pem"] = pkey.export_pem()

    if not s.exists("cert.pem"):
        key = crypto.load_privatekey(crypto.FILETYPE_PEM, pkey.export_pem())
        cert = crypto.X509()
        subj = cert.get_subject()
        subj.C = subj.ST = subj.L = "XX"
        subj.O = "FLUX3dp"
        subj.CN = (get_uuid() + ":" + get_serial() + ":")

        ext = crypto.X509Extension("nsComment", True, get_identify())
        cert.add_extensions((ext, ))

        cert.set_serial_number(1000)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(10 * 365 * 24 * 60 * 60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(key)
        cert.sign(key, 'sha1')
        s["cert.pem"] = crypto.dump_certificate(crypto.FILETYPE_PEM, cert)

    return s.get_path("cert.pem"), s.get_path("sslkey.pem")


class SSLInterface(InterfaceBase):
    def create_socket(self, endpoint):
        self.certfile, self.keyfile = prepare_cert()

        logger.info("Listen on %s:%i", *endpoint)
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(endpoint)
        s.listen(2)
        return s


class SSLConnectionHandler(HandlerBase):
    send_watcher = None
    binary_mode = False
    delegate = None
    access_id = None
    ready = 0

    def __init__(self, kernel, sock, endpoint, certfile, keyfile):
        self.logger = logger.getChild("%s:%s" % endpoint)
        self.logger.debug("Connected")
        sock.setblocking(False)
        super(SSLConnectionHandler, self).__init__(kernel, sock, endpoint)

        try:
            self.randbytes = randbytes(64)

            sock.send(b"FLUX0003")
            self.sock = ssl.SSLSocket(sock, certfile=certfile, keyfile=keyfile,
                                      server_side=True,
                                      do_handshake_on_connect=False)

        except Exception:
            # Ensure clean all resources
            self.close()
            raise

    def _on_ssl_handshake(self, watcher=None, revent=None):
        if self.send_watcher:
            self.send_watcher.stop()
            self.send_watcher = None

        try:
            self.sock.do_handshake()
            self.sock.send(self.randbytes)

            # SSL Handshake ready, prepare buffer
            self._buf = bytearray(4096)
            self._bufview = memoryview(self._buf)
            self._buffered = 0
            self.ready = 1

        except ssl.SSLWantReadError:
            pass
        except ssl.SSLWantWriteError:
            self.send_watcher = self.kernel.loop.io(
                self.sock, pyev.EV_WRITE, self._do_ssl_handshake)
        except Exception:
            logger.exception("SSL handshake failed")
            self.close()

    def _on_identify_handshake(self):
        if self._buffered > 20 and not self.access_id:
            self.access_id = aid = to_hex(self._buf[:20])

            if is_trusted_remote(aid):
                self.remotekey = get_keyobj(access_id=aid)
            else:
                self._final_handshake(MESSAGE_UNKNOWN_HOST, False)
                return

            length = 20 + self.remotekey.size()
            if self._buffered < length:
                pass
            elif self._buffered == length:
                document = hash_password(UUID_BIN, self.randbytes)
                self.remotekey.verify(document, self._buf[24:length])
                self._final_handshake(MESSAGE_OK, True)
            else:
                self.sock.send(MESSAGE_PROTOCOL_ERROR, False)

    def _final_handshake(self, message, success, log_message=None):
        if success:
            self.logger.info("Connected (access_id=%s)", self.access_id)
            self.sock.send(message)
            self._buffered = 0
            self._on_ready()
        else:
            self.logger.info("Connection rejected")
            self.sock.send(message)
            raise SystemError(log_message)

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
        if self.ready > 0:  # ready > 0
            while True:
                try:
                    l = self.sock.recv_into(self._bufview[self._buffered:])
                except ssl.SSLWantReadError:
                    return
                except Exception as e:
                    logger.error("SSL Socket recv error: %s", e)
                    self.close()
                    return

                try:
                    if l:
                        self._buffered += l
                        if self.ready > 1:
                            self._on_message()
                        else:
                            self._on_identify_handshake()

                    else:
                        self.close("CONNECTION_GONE")

                    if self.sock.pending() == 0:
                        return

                except Exception:
                    logger.exception("Unhandle error on recv interface, "
                                     "disconnect")
                    self.close()
                except SystemError as e:
                    logger.error("%s", repr(e))
                    self.close()
        else:
            self._on_ssl_handshake()

    def _on_ready(self):
        self.ready = 2
        self.on_ready()

    def _on_message(self):
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
            sent = self.sock.send(buf)
            while sent < length:
                sent += self.sock.send(buf[sent:])
            return length
        except ssl.SSLError as e:
            raise SystemError("SOCKET_ERROR", "SSL", repr(e))

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
        self.ready = -1
        if message:
            self.logger.info("Client disconnected (reason=%s)", message)
        if self.delegate:
            self.delegate.on_close(self)
            self.delegate = None
        super(SSLConnectionHandler, self).close()
