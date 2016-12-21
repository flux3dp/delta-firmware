
import logging
import socket
import os

import pyev

from fluxmonitor.config import MAINBOARD_ENDPOINT, HEADBOARD_ENDPOINT, \
    PC_ENDPOINT
from fluxmonitor.storage import Storage

logger = logging.getLogger("halservice.base")


class UartHalBase(object):
    hal_name = "BASE"
    support_hal = []

    def __init__(self, kernel):
        self.kernel = kernel
        self.storage = Storage("general", "mainboard")

        self.mainboard = self.create_socket(
            loop=kernel.loop, path=MAINBOARD_ENDPOINT,
            callback=self.on_connected_mainboard)
        self.headboard = self.create_socket(
            loop=kernel.loop, path=HEADBOARD_ENDPOINT,
            callback=self.on_connected_headboard)
        self.pc = self.create_socket(
            loop=kernel.loop, path=PC_ENDPOINT,
            callback=self.on_connected_pc)

        self.mainboard_watchers = []
        self.headboard_watchers = []
        self.pc_watchers = []

    def create_socket(self, loop, path, callback=None):
        if os.path.exists(path):
            os.unlink(path)

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(path)
        s.listen(1)
        w = loop.io(s, pyev.EV_READ, callback, s)
        w.start()
        return (w, s)

    def on_connected_mainboard(self, watcher, revent):
        logger.debug("Connect to mainboard")
        request, _ = watcher.data.accept()
        request.setblocking(False)
        watcher = watcher.loop.io(request, pyev.EV_READ,
                                  self.on_sendto_mainboard, request)
        watcher.start()
        self.mainboard_watchers.append(watcher)

    def on_disconnect_mainboard(self, watcher):
        watcher.stop()
        watcher.data.close()
        self.mainboard_watchers.remove(watcher)

    def on_connected_headboard(self, watcher, revent):
        logger.debug("Connect to headboard")
        request, _ = watcher.data.accept()
        request.setblocking(False)
        watcher = watcher.loop.io(request, pyev.EV_READ,
                                  self.on_sendto_headboard, request)
        watcher.start()
        self.headboard_watchers.append(watcher)

    def on_disconnect_headboard(self, watcher):
        watcher.stop()
        watcher.data.close()
        self.headboard_watchers.remove(watcher)

    def on_connected_pc(self, watcher, revent):
        logger.debug("Connect to pc")
        request, _ = watcher.data.accept()
        request.setblocking(False)
        watcher = watcher.loop.io(request, pyev.EV_READ,
                                  self.on_sendto_pc, request)
        watcher.start()
        self.pc_watchers.append(watcher)

    def on_disconnect_pc(self, watcher):
        watcher.stop()
        watcher.data.close()
        self.pc_watchers.remove(watcher)

    def on_sendto_mainboard(self, watcher, revent):
        try:
            buf = watcher.data.recv(1024)
            if buf:
                self.sendto_mainboard(buf)
            else:
                self.on_disconnect_mainboard(watcher)
        except IOError:
            self.on_disconnect_mainboard(watcher)
            return

    def on_sendto_headboard(self, watcher, revent):
        try:
            buf = watcher.data.recv(1024)
            if buf:
                self.sendto_headboard(buf)
            else:
                self.on_disconnect_headboard(watcher)
        except IOError:
            self.on_disconnect_headboard(watcher)
            return

    def on_sendto_pc(self, watcher, revent):
        buf = watcher.data.recv(1024)
        if buf:
            self.sendto_pc(buf)
        else:
            self.on_disconnect_pc(watcher)

    def sendto_mainboard(self, buf):
        pass

    def sendto_headboard(self, buf):
        pass

    def sendto_pc(self, buf):
        pass

    def start(self):
        pass

    def close(self):
        for watcher in self.mainboard_watchers:
            watcher.stop()
            watcher.data.close()
        for watcher in self.headboard_watchers:
            watcher.stop()
            watcher.data.close()
        for watcher in self.pc_watchers:
            watcher.stop()
            watcher.data.close()


class BaseOnSerial(object):
    def on_recvfrom_mainboard(self, watcher, revent):
        buf = watcher.data.read(4096)
        for w in self.mainboard_watchers:
            try:
                w.data.send(buf)
            except Exception:
                logger.error("Send mainboard message to %s failed", w.data)
        return buf

    def on_recvfrom_headboard(self, watcher, revent):
        buf = watcher.data.read(4096)
        for w in self.headboard_watchers:
            try:
                w.data.send(buf)
            except Exception:
                logger.error("Send headboard message to %s failed", w.data)
        return buf

    def on_recvfrom_pc(self, watcher, revent):
        buf = watcher.data.read(4096)
        for w in self.pc_watchers:
            try:
                w.data.send(buf)
            except Exception:
                logger.error("Send usb message to %s failed", w.data)
        return buf
