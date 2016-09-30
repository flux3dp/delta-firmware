
from binascii import b2a_hex as to_hex, a2b_hex as from_hex
from struct import Struct
from errno import EINPROGRESS
import logging
import socket
import ssl
import os

from fluxmonitor.security import (is_trusted_remote, get_keyobj, get_uuid,
                                  hash_password)
from fluxmonitor.misc import timer as T  # noqa
import pyev

SHORT_PACKER = Struct("<H")
logger = logging.getLogger(__name__)
__handlers__ = set()


class UDPHandler(object):
    def __init__(self, kernel, endpoint):
        self.kernel = kernel
        self.endpoint = endpoint

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.watcher = kernel.loop.io(self.sock.fileno(), pyev.EV_READ,
                                      self.on_recv)
        self.watcher.start()
        __handlers__.add(self)

    def on_recv(self, watcher, revent):
        try:
            buf, endpoint = self.sock.recvfrom(4096)
            self.on_message(buf, endpoint)
        except Exception:
            logger.exception("Unhandle error in udp handler")
            self.on_error()

    def send(self, buf):
        self.sock.sendto(buf, self.endpoint)

    def sendto(self, buf, endpoint):
        self.sock.sendto(buf, endpoint)

    def on_message(self, buf, endpoint):
        pass

    def close(self):
        logger.debug("UDP Closed")
        self.watcher.stop()
        self.sock.close()
        if self in __handlers__:
            __handlers__.remove(self)

    def on_error(self):
        self.close()


class TCPHandler(object):
    IDLE_TIMEOUT = 3600.  # Close conn if idel after seconds.

    @T.update_time
    def __init__(self, kernel, endpoint, sock=None):
        self.kernel = kernel
        self.endpoint = endpoint

        if sock:
            self.sock = sock
            self.watcher = kernel.loop.io(self.sock.fileno(),
                                          pyev.EV_READ | pyev.EV_WRITE,
                                          self._on_connecting)
            self.on_connected()
        else:
            self.sock = socket.socket()
            self.sock.setblocking(False)

            ret = self.sock.connect_ex((endpoint))
            assert ret == EINPROGRESS, "Async connect to endpoint error"

            self.watcher = kernel.loop.io(self.sock.fileno(),
                                          pyev.EV_READ | pyev.EV_WRITE,
                                          self._on_connecting)
            self.watcher.start()
        __handlers__.add(self)

    def send(self, buf):
        self.sock.send(buf)

    def recv(self, bufsize, flags=0):
        return self.sock.recv(bufsize, flags)

    def recvfrom(self, bufsize, flags=0):
        return self.sock.recvfrom(bufsize, flags)

    def recv_into(self, buffer, nbytes=0, flags=0):
        return self.sock.recv_into(buffer, nbytes, flags)

    @T.update_time
    def _on_connecting(self, watcher, revent):
        try:
            if revent & pyev.EV_READ:
                logger.debug("Async tcp connecting failed")
                self.on_error()
            else:
                self.on_connected()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    def close(self):
        logger.debug("TCP Closed")
        self.watcher.stop()
        self.sock.close()
        if self in __handlers__:
            __handlers__.remove(self)

    def on_connected(self):
        logger.debug("Connected")

    def on_error(self):
        self.close()


class SSLHandler(TCPHandler):
    def __init__(self, kernel, endpoint, sock=None, server_side=False,
                 certfile=None, keyfile=None):
        self.server_side = server_side
        self.certfile = certfile
        self.keyfile = keyfile
        super(SSLHandler, self).__init__(kernel, endpoint, sock)

    def on_connected(self):
        super(SSLHandler, self).on_connected()
        self.sock = ssl.wrap_socket(self.sock,
                                    server_side=self.server_side,
                                    certfile=self.certfile,
                                    keyfile=self.keyfile,
                                    do_handshake_on_connect=False)
        self.watcher.stop()
        self.watcher.callback = self._on_ssl_handshake
        self.watcher.set(self.sock.fileno(), pyev.EV_READ | pyev.EV_WRITE)
        self.watcher.start()

    @T.update_time
    def _on_ssl_handshake(self, watcher, revent):
        try:
            self.sock.do_handshake()
            self.on_ssl_connected()
        except ssl.SSLWantReadError:
            self.watcher.stop()
            self.watcher.set(self.sock.fileno(), pyev.EV_READ)
            self.watcher.start()
        except ssl.SSLWantWriteError:
            self.watcher.stop()
            self.watcher.set(self.sock.fileno(), pyev.EV_WRITE)
            self.watcher.start()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    def on_ssl_connected(self):
        logger.debug("SSL hahdshake completed")


MESSAGE_OK = b"OK              "
MESSAGE_AUTH_ERROR = b"AUTH_ERROR      "
MESSAGE_UNKNOWN_HOST = b"UNKNOWN_HOST    "
MESSAGE_PROTOCOL_ERROR = b"PROTOCOL_ERROR  "
UUID_HEX = get_uuid()
UUID_BIN = from_hex(UUID_HEX)


class SSLServerSideHandler(SSLHandler):
    access_id = None
    remotekey = None

    def on_connected(self):
        self.sock.send(b"FLUX0003")
        super(SSLServerSideHandler, self).on_connected()

    @T.update_time
    def _on_handshake_identify(self, watcher, revent):
        try:
            buf = self.sock.recv(4096)
            if buf:
                watcher.data += buf

                if len(watcher.data) > 20 and not self.access_id:
                    aid = to_hex(watcher.data[:20])
                    if is_trusted_remote(aid):
                        self.access_id = aid
                        self.remotekey = get_keyobj(access_id=aid)
                    else:
                        logger.debug("Unknown access id")
                        self.sock.send(MESSAGE_UNKNOWN_HOST)
                        self.close()
                        return

                    length = 20 + self.remotekey.size()
                    if len(watcher.data) < length:
                        pass
                    elif len(watcher.data) == length:
                        document = hash_password(UUID_BIN, self.randbytes)
                        self.remotekey.verify(document,
                                              watcher.data[24:length])
                        logger.debug("Connected with access id: %s",
                                     self.access_id)
                        self.sock.send(MESSAGE_OK)
                        self.on_authorized()
                    else:
                        logger.debug("Protocol error")
                        self.sock.send(MESSAGE_PROTOCOL_ERROR)
                        self.close()
            else:
                logger.debug("Connection closed")
                self.close()

        except Exception:
            logger.exception("Unhandle error")
            self.close()

    def on_ssl_connected(self):
        super(SSLServerSideHandler, self).on_ssl_connected()
        self.watcher.stop()
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.callback = self._on_handshake_identify
        self.watcher.data = b""
        self.randbytes = os.urandom(64)
        self.sock.send(self.randbytes)
        self.watcher.start()

    def on_authorized(self):
        pass


class CloudHandler(SSLHandler):
    on_close_cb = None

    def __init__(self, kernel, endpoint, token, on_close=None):
        super(CloudHandler, self).__init__(kernel, endpoint)
        self.on_close_cb = on_close
        self.token = token

    def on_ssl_connected(self):
        super(CloudHandler, self).on_ssl_connected()
        self.watcher.stop()
        self.watcher.set(self.sock.fileno(), pyev.EV_WRITE)
        self.watcher.callback = self._on_send_token
        self.watcher.start()

    @T.update_time
    def _on_send_token(self, watcher, revent):
        try:
            logger.debug("Cloud token sent")
            self.sock.send(self.token)
            self.watcher.stop()
            self.watcher.set(self.sock.fileno(), pyev.EV_READ)
            self.watcher.callback = self._on_complete_cloud_handshake
            self.watcher.start()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    @T.update_time
    def _on_complete_cloud_handshake(self, watcher, revent):
        try:
            buf = self.sock.recv(1)
            if buf:
                if buf == "\x00":
                    self.on_cloud_connected()
                else:
                    logger.error("Cloud return value %x at handshake",
                                 ord(buf))
                    self.close()
            else:
                logger.debug("Cloud connection during handshake")
                self.close()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    def on_cloud_connected(self):
        logger.debug("Cloud connected")

    def close(self):
        try:
            if self.on_close_cb:
                self.on_close_cb(self)
        finally:
            super(CloudHandler, self).close()


class TextBinaryProtocol(object):
    binary_mode = False

    @T.update_time
    def _on_send_binary(self, watcher, revent):
        try:
            length, sent_length, stream, callback = watcher.data
            buf = stream.read(min(length - sent_length, 4096))

            l = self.sock.send(buf)
            if l == 0:
                watcher.stop()
                logger.error("Socket %s send data length 0", self.sock)
                self.on_error()
                return

            sent_length += l
            stream.seek(l - len(buf), 1)

            if sent_length == length:
                logger.debug("Binary sent")
                watcher.stop()
                watcher.set(watcher.fd, pyev.EV_READ)
                watcher.callback = self.on_recv
                watcher.start()
                callback(self)

            elif sent_length > length:
                watcher.stop()
                logger.error("GG on socket %s", self.sock)
                self.on_error()

            else:
                watcher.data = (length, sent_length, stream, callback)

        except Exception:
            logger.exception("Unknow error")
            watcher.stop()
            self.on_error()

    def on_ready(self):
        self._buf = bytearray(4096)
        self._bufview = memoryview(self._buf)
        self._buffered = 0

        self.watcher.stop()
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.callback = self.on_recv
        self.watcher.start()

    @T.update_time
    def on_recv(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._bufview[self._buffered:])
            if l:
                self._buffered += l
                self._on_message()
            else:
                self.close()
        except OSError as e:
            logger.warning("Recv error: %s", e)
            self.close()
        except Exception:
            logger.exception("Unhandle error")
            self.close()

    def on_binary(self, buf):
        pass

    def on_text(self, text):
        pass

    def _on_message(self):
        if self.binary_mode:
            ret = self._buffered
            self._buffered = 0
            self.on_binary(bytes(self._buf[:ret]))
        else:
            while self._buffered > 2:
                # Try unpack
                l = SHORT_PACKER.unpack_from(self._buf)[0]
                if l > 4094:
                    logger.error("Text payload too large, disconnect.")
                    self.close()
                if self._buffered > l:
                    payload = self._bufview[2:l].tobytes()
                    self._bufview[:self._buffered - l] = \
                        self._bufview[l:self._buffered]
                    self._buffered -= l
                    self.on_text(payload.decode("utf8", "ignore"))
                elif self._buffered == l:
                    payload = self._bufview[2:l].tobytes()
                    self._buffered = 0
                    self.on_text(payload.decode("utf8", "ignore"))
                else:
                    break

    def send_text(self, message):
        if isinstance(message, unicode):
            bmessage = message.encode("utf8")
        else:
            bmessage = message
        l = len(bmessage)
        buf = SHORT_PACKER.pack(l) + bmessage
        return self.sock.send(buf)

    def begin_send(self, stream, length, complete_callback):
        if length > 0:
            self.watcher.stop()
            data = (length, 0, stream, complete_callback)
            self.watcher.data = data
            self.watcher.set(self.sock.fileno(), pyev.EV_WRITE)
            self.watcher.callback = self._on_send_binary
            self.watcher.start()
        else:
            complete_callback(self)
