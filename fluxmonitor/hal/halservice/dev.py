
import logging
import os

import pyev

logger = logging.getLogger(__name__)

from fluxmonitor.halprofile import MODEL_DARWIN_DEV, MODEL_LINUX_DEV
from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.config import general_config
from .base import UartHalBase

class UartHal(UartHalBase):
    hal_name = "dev"
    support_hal = [MODEL_DARWIN_DEV, MODEL_LINUX_DEV]

    def __init__(self, kernel):
        super(UartHal, self).__init__(kernel)

        p = general_config["db"]

        self.listen_mainboard = self.create_socket(kernel.loop,
            os.path.join(p, "mb"), self.on_fake_mainboard_connected)
        
        self.listen_headboard = self.create_socket(kernel.loop,
            os.path.join(p, "hb"), self.on_fake_headboard_connected)

        self.listen_pc = self.create_socket(kernel.loop,
            os.path.join(p, "pc"), self.on_fake_pc_connected)

        self.fake_mainboard_watchers = []
        self.fake_headboard_watchers = []
        self.fake_pc_watchers = []

    def on_fake_mainboard_connected(self, watcher, revent):
        logger.debug("Connect from mainboard")
        request, _ = watcher.data.accept()
        watcher = watcher.loop.io(request, pyev.EV_READ,
                                  self.on_recvfrom_mainboard, request)
        watcher.start()
        self.fake_mainboard_watchers.append(watcher)

    def on_fake_headboard_connected(self, watcher, revent):
        logger.debug("Connect from headboard")
        request, _ = watcher.data.accept()
        watcher = watcher.loop.io(request, pyev.EV_READ,
                                  self.on_recvfrom_headboard, request)
        watcher.start()
        self.fake_headboard_watchers.append(watcher)

    def on_fake_pc_connected(self, watcher, revent):
        logger.debug("Connect from pc")
        request, _ = watcher.data.accept()
        watcher = watcher.loop.io(request, pyev.EV_READ,
                                  self.on_recvfrom_pc, request)
        watcher.start()
        self.fake_pc_watchers.append(watcher)

    def on_recvfrom_mainboard(self, watcher, revent):
        buf = watcher.data.recv(1024)
        if buf:
            for w in self.mainboard_watchers:
                w.data.send(buf)
        else:
            watcher.stop()
            watcher.data.close()
            self.fake_mainboard_watchers.remove(watcher)

    def on_recvfrom_headboard(self, watcher, revent):
        buf = watcher.data.recv(1024)
        if buf:
            for w in self.headboard_watchers:
                w.data.send(buf)
        else:
            watcher.stop()
            watcher.data.close()
            self.fake_headboard_watchers.remove(watcher)

    def on_recvfrom_pc(self, watcher, revent):
        buf = watcher.data.recv(1024)
        if buf:
            for w in self.pc_watchers:
                w.data.send(buf)
        else:
            watcher.stop()
            watcher.data.close()
            self.fake_pc_watchers.remove(watcher)

    def sendto_mainboard(self, buf):
        for w in self.fake_mainboard_watchers:
            w.data.send(buf)

    def sendto_headboard(self, buf):
        for w in self.fake_headboard_watchers:
            w.data.send(buf)

    def sendto_pc(self, buf):
        for w in self.fake_pc_watchers:
            w.data.send(buf)
