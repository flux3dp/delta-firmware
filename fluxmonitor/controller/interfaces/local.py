
from binascii import b2a_hex as to_hex
import weakref
import logging
import struct
import socket
import os

import pyev

from fluxmonitor.controller.tasks.command_task import CommandTask
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.err_codes import AUTH_ERROR
from fluxmonitor.misc import timer as T
from fluxmonitor import security

logger = logging.getLogger(__name__)
IDLE_TIMEOUT = 3600.  # Close conn if idel after seconds.


class LocalControl(object):
    def __init__(self, kernel, port=23811):
        self.logger = logger
        self.meta = CommonMetadata()

        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))

        self.listen_watcher = kernel.loop.io(s, pyev.EV_READ, self.on_accept,
                                             s)
        self.listen_watcher.start()
        self.timer_watcher = kernel.loop.timer(30, 30, self.on_timer)
        self.timer_watcher.start()

        self.clients = []
        logger.info("Listen on %s:%i" % ("", port))

        s.listen(2)

    def on_accept(self, watcher, revent):
        try:
            sock, endpoint = watcher.data.accept()

            try:
                pkey = security.RSAObject(der=self.meta.shared_der_rsakey)
            except RuntimeError:
                logger.error("Slave key not ready, use master key instead")
                pkey = security.get_private_key()

            handler = LocalConnectionHandler(sock, endpoint, pkey,
                                             watcher.loop)
            self.clients.append(handler)
        except Exception:
            logger.exception("Unhandle Error")
            sock.close()

    def on_timer(self, watcher, revent):
        zombie = []
        for h in self.clients:
            if (not h.alive) or h.is_timeout:
                zombie.append(h)

        for h in zombie:
            h.close("Timeout")
            logger.debug("Clean zombie %s", h)
            self.clients.remove(h)

    def close(self):
        self.timer_watcher.stop()
        self.timer_watcher = None
        self.listen_watcher.stop()
        self.listen_watcher = None

        while self.clients:
            h = self.clients.pop()
            h.close()


class LocalConnectionHandler(object):
    send_watcher = None

    @T.update_time
    def __init__(self, sock, endpoint, slave_key, loop):
        self.logger = logger.getChild("%s:%s" % endpoint)
        self.binary_mode = False

        self.alive = True
        self.ready = False
        self.stack = None

        self.rsakey = slave_key

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
        self.recv_watcher = loop.io(sock, pyev.EV_READ, self.on_recv)
        self.recv_watcher.start()

    @property
    def kernel(self):
        return self.recv_watcher.loop.data

    @property
    def address(self):
        try:
            ipaddr = self.sock.getpeername()[0]
            try:
                return socket.gethostbyaddr(ipaddr)[0]
            except Exception:
                return ipaddr
        except (OSError, socket.error):
            return "ZOMBIE"

    @property
    def is_timeout(self):
        return T.time_since_update(self) > IDLE_TIMEOUT

    @T.update_time
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

    @T.update_time
    def on_send(self, watcher, revent):
        length, sent_length, stream, callback = watcher.data

        buf = stream.read(min(length - sent_length, 4096))
        try:
            l = self.send(buf)
            if l == 0:
                self.close("Socket send 0")
                return

            sent_length += l
            stream.seek(l - len(buf), 1)

            if sent_length == length:
                self.recv_watcher.start()

                logger.debug("Binary sent")
                watcher.stop()
                self.send_watcher = None
                callback(self)

            elif sent_length > length:
                self.close("GG")

            else:
                watcher.data = (length, sent_length, stream, callback)

        except socket.error as e:
            self.close(repr(e))
        except Exception:
            logger.exception("Unknow error")

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
            self._on_ready()
            self.logger.info("Connected (access_id=%s)", self.access_id)
            self.sock.send(message)

            aes_key, aes_iv = os.urandom(32), os.urandom(16)
            self.aes = security.AESObject(aes_key, aes_iv)
            self.sock.send(self.keyobj.encrypt(aes_key + aes_iv))
            self._buffered = 0
        else:
            self.logger.info("Handshake fail (%s)", log_message)
            self.sock.send(message)
            self.close()

    def _on_ready(self):
        self.ready = True
        self.stack = ServiceStack(self.recv_watcher.loop)

    def _on_message(self, length):
        chunk = self._bufview[self._buffered - length:self._buffered]
        self.aes.decrypt_into(chunk, chunk)

        if self.binary_mode:
            ret = self._buffered
            self._buffered = 0
            self.stack.on_binary(bytes(self._buf[:ret]), self)
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
                    self.stack.on_text(payload.decode("utf8", "ignore"), self)
                elif self._buffered == l:
                    payload = self._bufview[2:l].tobytes()
                    self._buffered = 0
                    self.stack.on_text(payload.decode("utf8", "ignore"), self)
                else:
                    break

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

    def async_send_binary(self, mimetype, length, stream, complete_cb):
        self.send_text("binary %s %i" % (mimetype, length))
        if length > 0:
            self.recv_watcher.stop()

            self.send_watcher = self.recv_watcher.loop.io(
                self.sock, pyev.EV_WRITE, self.on_send, (length, 0, stream,
                                                         complete_cb))
            self.send_watcher.start()
        else:
            complete_cb(self)

    def close(self, reason=""):
        if self.alive:
            self.alive = False
            self.recv_watcher.stop()
            self.recv_watcher = None

            if self.send_watcher:
                self.send_watcher.stop()
                self.send_watcher = None

            self.sock.close()
            if self.stack:
                self.stack.terminate()
                self.stack = None

            if reason:
                self.logger.info("Client disconnected (reason=%s)", reason)


class ServiceStack(object):
    def __init__(self, loop):
        self.loop = loop
        self.task_callstack = []
        self.this_task = None

        cmd_task = CommandTask(weakref.proxy(self))
        self.enter_task(cmd_task, None)

    def __del__(self):
        logger.debug("ServiceStack GC")

    @property
    def kernel(self):
        return self.loop.data

    def on_text(self, message, handler):
        self.this_task.on_text(message, handler)

    def on_binary(self, buf, handler):
        self.this_task.on_binary(buf, handler)

    def enter_task(self, invoke_task, return_callback):
        logger.debug("Enter %s" % invoke_task.__class__.__name__)
        self.task_callstack.append((self.this_task, return_callback))
        self.this_task = invoke_task

    def exit_task(self, task, *return_args):
        if self.this_task != task:
            raise Exception("Task not match")

        try:
            task.on_exit()
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)

        try:
            current_task, callback = self.task_callstack.pop()
            callback(*return_args)
            logger.debug("Exit %s" % self.this_task.__class__.__name__)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)
        finally:
            self.this_task = current_task

    def terminate(self):
        while len(self.task_callstack) > 2:
            task, cb = self.task_callstack.pop()
            try:
                task.on_exit()
            except Exception:
                logger.exception("Unhandle error")
