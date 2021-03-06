
from weakref import WeakSet, proxy
import logging
import socket
import os

import pyev

from fluxmonitor.storage import Metadata
from fluxmonitor import security

__all__ = ["TcpInterface", "SSLInterface"]
logger = logging.getLogger(__name__)


class StreamInterfaceBase(object):
    def __init__(self, kernel, endpoint=None, handler=None):
        self.kernel = proxy(kernel)
        self.handler = handler
        self.meta = Metadata()

        s = self.create_socket(endpoint)
        self.listen_w = kernel.loop.io(s, pyev.EV_READ, self.on_accept, s)
        self.listen_w.start()
        self.timer_w = kernel.loop.timer(30, 30, self.on_timer)
        self.timer_w.start()

        self.clients = WeakSet()

    @property
    def alive(self):
        return self.listen_w is not None

    def create_socket(self, endpoint):
        pass

    def create_handler(self, sock, endpoint):
        h = self.handler(self.kernel, sock, endpoint)
        return h

    def getsocket(self):
        if self.listen_w:
            return self.listen_w.data

    def on_accept(self, watcher, revent):
        sock, endpoint = watcher.data.accept()
        try:
            sock.settimeout(3)
            handler = self.create_handler(sock, endpoint)
            self.clients.add(handler)
        except Exception:
            logger.exception("Unhandle error while create connection handler")
            sock.close()

    def on_timer(self, watcher, revent):
        zombie = []
        for h in self.clients:
            if (not h.alive) or h.is_timeout:
                zombie.append(h)

        for h in zombie:
            if h.alive:
                logger.debug("%s connection timeout", h)
                h.close()
            else:
                logger.debug("Clean zombie connection %s", h)

            self.clients.remove(h)

    def close(self):
        if self.listen_w:
            self.timer_w.stop()
            self.timer_w = None
            self.listen_w.stop()
            self.listen_w.data.close()
            self.listen_w = None

            while self.clients:
                h = self.clients.pop()
                h.close()


class DiagramInterfaceBase(object):
    def __init__(self, kernel, endpoint, onmessage_callback=None):
        self.kernel = proxy(kernel)
        s = self.create_socket(endpoint)
        self._sock_w = kernel.loop.io(s, pyev.EV_READ, self.on_recv, s)
        self._sock_w.start()

    @property
    def alive(self):
        return self._sock_w is not None

    def create_socket(self, endpoint):
        pass

    def getsocket(self):
        if self._sock_w:
            return self._sock_w.data

    def on_recv(self, watcher, revent):
        buf, endpoint = watcher.data.recvfrom(4096)
        self.on_message(buf, endpoint)

    def on_message(self, buf, endpoint):
        pass

    def sendto(self, buf, endpoint):
        if endpoint:
            self._sock_w.data.sendto(buf, endpoint)

    def close(self):
        if self._sock_w:
            self._sock_w.stop()
            self._sock_w.data.close()
            self._sock_w = None


class TcpInterface(StreamInterfaceBase):
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


class SSLInterface(StreamInterfaceBase):
    def create_socket(self, endpoint):
        self.certfile, self.keyfile = security.get_cert()

        logger.info("Listen on %s:%i", *endpoint)
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(endpoint)
        s.listen(2)
        return s


class UnixsocketMixIn(object):
    def bind_socket(self, endpoint, type):
        if os.path.exists(endpoint):
            logger.info("Unlink '%s' for new unix socket", endpoint)
            os.unlink(endpoint)
        logger.info("Listen on '%s'", endpoint)
        s = socket.socket(socket.AF_UNIX, type)
        s.bind(endpoint)
        return s


class UnixDgrmInterface(DiagramInterfaceBase, UnixsocketMixIn):
    def create_socket(self, endpoint):
        return self.bind_socket(endpoint, socket.SOCK_DGRAM)

    def close(self):
        if self.alive:
            endpoint = self.getsocket().getsockname()
            super(UnixDgrmInterface, self).close()
            os.unlink(endpoint)


class UnixStreamInterface(StreamInterfaceBase, UnixsocketMixIn):
    def create_socket(self, endpoint):
        s = self.bind_socket(endpoint, socket.SOCK_STREAM)
        s.listen(2)
        return s

    def close(self):
        if self.alive:
            endpoint = self.getsocket().getsockname()
            super(UnixStreamInterface, self).close()
            os.unlink(endpoint)
