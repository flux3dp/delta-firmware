
from weakref import WeakSet, proxy
import logging
import abc

import pyev

from fluxmonitor.storage import Metadata
from fluxmonitor.misc import timer as T  # noqa

__all__ = ["InterfaceBase", "HandlerBase"]

logger = logging.getLogger(__name__)
__handlers__ = set()


class InterfaceBase(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, kernel, endpoint=None):
        self.kernel = proxy(kernel)
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

    @abc.abstractmethod
    def create_socket(self, endpoint):
        pass

    @abc.abstractmethod
    def create_handler(self, sock, endpoint):
        pass

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
            h.close("Timeout")
            logger.debug("Clean zombie %s", h)
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


class HandlerBase(object):
    IDLE_TIMEOUT = 3600.  # Close conn if idel after seconds.

    @T.update_time
    def __init__(self, kernel, sock, endpoint):
        self.sock = sock
        self.kernel = kernel
        self.recv_watcher = kernel.loop.io(sock, pyev.EV_READ, self._on_recv)
        self.recv_watcher.start()
        __handlers__.add(self)

    @T.update_time
    def _on_recv(self, watcher, revent):
        self.on_recv(watcher, revent)

    @abc.abstractmethod
    def on_recv(self, watcher, revent):
        pass

    @abc.abstractmethod
    def send(self, buf):
        pass

    @T.update_time
    def _on_send(self, watcher, revent):
        try:
            length, sent_length, stream, callback = watcher.data
            buf = stream.read(min(length - sent_length, 4096))

            l = self.send(buf)
            if l == 0:
                watcher.stop()
                self.send_watcher = None
                logger.error("Socket %s send data length 0", self.sock)
                self.close()
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
                watcher.stop()
                self.send_watcher = None
                logger.error("GG on socket %s", self.sock)
                self.close()

            else:
                watcher.data = (length, sent_length, stream, callback)

        except ConnectionClosedException as e:
            logger.debug("%s", e)
            watcher.stop()
            self.send_watcher = None
            self.close()

        except SystemError as e:
            logger.debug("System error: %s", e)
            watcher.stop()
            self.send_watcher = None
            self.close()

        except Exception:
            logger.exception("Unknow error")
            watcher.stop()
            self.send_watcher = None
            self.close()

    def begin_send(self, stream, length, complete_callback):
        if length > 0:
            self.recv_watcher.stop()
            data = (length, 0, stream, complete_callback)
            self.send_watcher = self.kernel.loop.io(
                self.sock, pyev.EV_WRITE, self._on_send, data)
            self.send_watcher.start()
        else:
            complete_callback(self)

    @property
    def alive(self):
        return self.sock is not None

    @property
    def is_timeout(self):
        return T.time_since_update(self) > self.IDLE_TIMEOUT

    def close(self):
        if self.sock:
            self.recv_watcher.stop()
            self.recv_watcher = None
            self.sock.close()
            self.sock = None

        if self in __handlers__:
            __handlers__.remove(self)


class ConnectionClosedException(Exception):
    pass
