
from binascii import b2a_hex as to_hex, a2b_hex as from_hex
from struct import Struct
from errno import EINPROGRESS, errorcode
import msgpack
import logging
import socket
import ssl
import os

from fluxmonitor.err_codes import AUTH_ERROR
from fluxmonitor.security import (is_trusted_remote, get_keyobj, get_uuid,
                                  hash_password, AESObject)
from fluxmonitor.misc import timer as T  # noqa
import pyev

SHORT_PACKER = Struct("<H")
logger = logging.getLogger(__name__)
__handlers__ = set()


class SocketHandler(object):
    IDLE_TIMEOUT = 3600.  # Close conn if idel after seconds.
    watcher = None
    sock = None

    @property
    def alive(self):
        try:
            self.sock.fileno()
            return True
        except IOError:
            return False

    @property
    def address(self):
        pass

    @property
    def is_timeout(self):
        return T.time_since_update(self) > self.IDLE_TIMEOUT

    def send(self, buf):
        self.sock.send(buf)

    def recv(self, bufsize, flags=0):
        return self.sock.recv(bufsize, flags)

    def recvfrom(self, bufsize, flags=0):
        return self.sock.recvfrom(bufsize, flags)

    def recv_into(self, buffer, nbytes=0, flags=0):
        return self.sock.recv_into(buffer, nbytes, flags)

    def on_connected(self):
        logger.debug("%s Connected", self)

    @T.update_time
    def _on_connecting(self, watcher, revent):
        try:
            if revent & pyev.EV_READ:
                logger.debug("Async socket connecting failed")
                self.on_error()
            else:
                self.on_connected()
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    def on_error(self):
        logger.debug("%s socket error", self)
        self.close()

    def close(self):
        logger.debug("%s Closed", self)
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        self.sock.close()
        if self in __handlers__:
            __handlers__.remove(self)

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__, self.address)


class TCPHandler(SocketHandler):
    _address = None

    @T.update_time
    def __init__(self, kernel, endpoint, sock=None):
        self.kernel = kernel
        self.endpoint = endpoint

        if sock:
            self.sock = sock
            self.sock.setblocking(False)
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

    @property
    def address(self):
        if self._address is None:
            try:
                self._address = socket.gethostbyaddr(self.endpoint[0])[0]
            except Exception:
                self._address = self.endpoint[0]
        return self._address


class UnixHandler(SocketHandler):
    on_connected_cb = None
    on_close_cb = None

    @T.update_time
    def __init__(self, kernel, endpoint, sock=None, dgram=False,
                 on_connected_callback=None, on_close_callback=None):
        self.kernel = kernel
        self.endpoint = endpoint
        self.dgram = dgram
        self._on_connected_cb = on_connected_callback
        self._on_close_cb = on_close_callback

        if sock:
            self.sock = sock
            self.sock.setblocking(False)
            self.watcher = kernel.loop.io(self.sock.fileno(),
                                          pyev.EV_READ | pyev.EV_WRITE,
                                          self._on_connecting)
            self.on_connected()
        else:
            sock_type = socket.SOCK_DGRAM if dgram else socket.SOCK_STREAM
            self.sock = socket.socket(socket.AF_UNIX, sock_type)
            self.sock.setblocking(False)

            ret = self.sock.connect_ex(endpoint)
            if ret != 0:
                raise IOError("Async connect to endpoint error: %s" %
                              errorcode.get(ret))

            self.watcher = kernel.loop.io(self.sock.fileno(),
                                          pyev.EV_READ | pyev.EV_WRITE,
                                          self._on_connecting)
            self.watcher.start()
        __handlers__.add(self)

    @property
    def address(self):
        return self.endpoint

    def on_connected(self):
        super(UnixHandler, self).on_connected()
        if self._on_connected_cb:
            self._on_connected_cb(self)

    def on_error(self):
        logger.debug("%s socket error", self)
        self.close(error=True)

    def close(self, error=False):
        try:
            if self._on_close_cb:
                self._on_close_cb(self, error)
        finally:
            super(UnixHandler, self).close()


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
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
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
                        self.on_error()
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
                        self.on_error()
            else:
                logger.debug("Connection closed")
                self.on_error()
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

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
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    @T.update_time
    def _on_complete_cloud_handshake(self, watcher, revent):
        try:
            buf = self.sock.recv(1)
            if buf == b"\x00":
                self.on_cloud_connected()
            elif buf != b"":
                logger.error("Cloud return value %x at handshake",
                             ord(buf))
                self.on_error()
            else:
                logger.debug("Cloud connection during handshake")
                self.on_error()
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
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


class MsgpackProtocol(object):
    def on_ready(self, max_buffer_size=2048):
        self.unpacker = msgpack.Unpacker(use_list=False,
                                         max_buffer_size=max_buffer_size)
        self.watcher.stop()
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.callback = self.on_recv
        self.watcher.start()

    @T.update_time
    def _on_send_binary(self, watcher, revent):
        if revent & pyev.EV_READ:
            if self.sock.recv(1) != b"\x00":
                logger.warning("Msgpack binary protocol error")
                self.on_error()
            else:
                self.watcher.stop()
                self.watcher.set(self.sock.fileno(), pyev.EV_WRITE)
                self.watcher.start()

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

        except IOError as e:
            logger.debug("Send error: %s", e)
            watcher.stop()
            self.on_error()
        except Exception:
            logger.exception("Unknow error")
            watcher.stop()
            self.on_error()

    def begin_send(self, stream, length, complete_callback):
        if length > 0:
            self.watcher.stop()
            data = (length, 0, stream, complete_callback)
            self.watcher.data = data
            self.watcher.set(self.sock.fileno(), pyev.EV_READ)
            self.watcher.callback = self._on_send_binary
            self.watcher.start()
        else:
            complete_callback(self)

    def send_payload(self, payload):
        buf = msgpack.packb(payload)
        self.send(buf)

    @T.update_time
    def on_recv(self, watcher, revent):
        try:
            buf = self.sock.recv(2048)
            if buf:
                self.unpacker.feed(buf)
                for data in self.unpacker:
                    self.on_payload(data)
            else:
                self.on_error()
        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
        except Exception:
            logger.exception("Unhandle error in msgpack recv")
            self.on_error()

    def on_payload(self, data):
        pass


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

        except IOError as e:
            logger.debug("%r Async send error: %s", self, e)
            watcher.stop()
            self.on_error()
        except Exception:
            logger.exception("%r Unknow error", self)
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

    @property
    def on_recv(self):
        # Note: ssl wrapped socket has a special behavior,
        # read python ssl module non-blocking sockets session for more details.
        if hasattr(self.sock, "pending"):
            return self.on_recv_ssl
        else:
            return self.on_recv_default

    @T.update_time
    def on_recv_default(self, watcher, revent):
        try:
            l = self.sock.recv_into(self._bufview[self._buffered:])
            if l:
                self._buffered += l
                self._on_message()
            else:
                self.close()
        except ssl.SSLError as e:
            logger.debug("SSL Connection error: %s", e)
            self.on_error()
        except IOError as e:
            logger.warning("Recv error: %s", e)
            self.on_error()
        except Exception:
            logger.exception("Unhandle error")
            self.on_error()

    def on_recv_ssl(self, watcher, revent):
        self.on_recv_default(watcher, revent)
        while self.sock.pending():
            self.on_recv_default(watcher, revent)

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
                    logger.error("Text payload too large (%i), disconnect.", l)
                    self.close()
                if l < 3:
                    logger.error("Text payload too short (%i), disconnect.", l)
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


class AESSocket(object):
    def __init__(self, sock, aes):
        self.sock = sock
        self.aes = aes

    def fileno(self):
        return self.sock.fileno()

    def send(self, buf):
        buf = memoryview(self.aes.encrypt(buf))
        l = len(buf)
        sl = 0
        while sl < l:
            s = self.sock.send(buf[sl:])
            if s:
                sl += s
            else:
                raise IOError("Connection closed")
        return l

    def recv_into(self, view):
        l = self.sock.recv_into(view)
        if l:
            self.aes.decrypt_into(view[:l], view[:l])
        return l

    def close(self):
        self.sock.close()


class OldAesServerSideHandler(TCPHandler):
    def __init__(self, kernel, endpoint, sock=None, privatekey=None):
        self.rsakey = privatekey
        self.logger = logger.getChild("%s:%s" % endpoint)
        super(OldAesServerSideHandler, self).__init__(kernel, endpoint, sock)

    def on_connected(self):
        super(OldAesServerSideHandler, self).on_connected()
        self.randbytes = os.urandom(128)

        # Send handshake payload:
        #    "FLUX0002" (8 bytes)
        #    signed random bytes (private keysize)
        #    random bytes (128 bytes)
        buf = b"FLUX0002" + \
              self.rsakey.sign(self.randbytes) + \
              self.randbytes
        self.sock.send(buf)

        # self._buf = bytearray(4096)
        # self._bufview = memoryview(self._buf)
        # self._buffered = 0

        self.watcher.data = ""
        self.watcher.stop()
        self.watcher.set(self.sock.fileno(), pyev.EV_READ)
        self.watcher.callback = self._on_auth_recv
        self.watcher.start()

    @T.update_time
    def _on_auth_recv(self, watcher, revent):
        try:
            buf = self.sock.recv(4096)
            if buf:
                self.watcher.data += buf
                self._on_handshake_identify(self.watcher.data)
            else:
                self.on_error()

        except IOError as e:
            logger.debug("%s", e)
            self.on_error()
        except Exception as e:
            logger.exception("Unknown error on auth recv")
            self.on_error()

    def _on_handshake_identify(self, data):
        if len(data) >= 20:
            access_id = to_hex(data[:20])
            if access_id == "0" * 40:
                raise RuntimeError("Not implement")
            else:
                self.access_id = access_id
                self.logger.debug("Access ID: %s" % access_id)
                self.keyobj = get_keyobj(access_id=access_id)

                if self.keyobj:
                    if len(data) >= (20 + self.keyobj.size()):
                        self._on_handshake_validate(data)
                else:
                    self._reply_handshake(AUTH_ERROR, success=False,
                                          log_message="Unknow Access ID")

    def _on_handshake_validate(self, data):
        """
        Recive handshake payload:
            access id (20 bytes)
            signature (remote private key size)

        Send final handshake payload:
            message (16 bytes)
        """
        req_hanshake_len = 20 + self.keyobj.size()

        if len(data) > req_hanshake_len:
            self._reply_handshake(b"PROTOCOL_ERROR", success=False,
                                  log_message="Handshake message too long")

        elif len(data) == req_hanshake_len:
            signature = data[20:req_hanshake_len]

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
            self.aes = AESObject(aes_key, aes_iv)
            self.sock.send(self.keyobj.encrypt(aes_key + aes_iv))
            self._buffered = 0
            self.on_authorized()
        else:
            self.logger.info("Handshake fail (%s)", log_message)
            self.sock.send(message)
            self.on_error()

    def on_authorized(self):
        self.sock = AESSocket(self.sock, self.aes)
