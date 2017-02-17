
from errno import ECONNREFUSED, ENOENT
from shlex import split as shlex_split
import logging
import socket

import pyev

from fluxmonitor.err_codes import SUBSYSTEM_ERROR, NO_RESPONSE, UNKNOWN_ERROR
from fluxmonitor.config import MAINBOARD_ENDPOINT, HEADBOARD_ENDPOINT, DEBUG
from fluxmonitor.hal import tools

logger = logging.getLogger(__name__)


class CommandMixIn(object):
    def on_text(self, buf, handler):
        try:
            cmd = buf.rstrip("\x00\n\r")

            if cmd == "position":
                handler.send_text(self.__class__.__name__)
            else:
                # NOTE: PY27
                if isinstance(buf, unicode):
                    params = [p.decode("utf8")
                              for p in shlex_split(cmd.encode("utf8"))]
                else:
                    params = shlex_split(cmd)
                response = self.dispatch_cmd(handler, *params)
                if response is not None:
                    logger.error("Shoud not response anything")
                    handler.send_text(response)

        except RuntimeError as e:
            handler.send_text(("error " + " ".join(e.args)).encode())

        except IOError as e:
            logger.debug("Connection close: %s" % e)
            handler.close()

        except Exception as e:
            if DEBUG:
                handler.send_text("error %s %s" % (UNKNOWN_ERROR, e))
            else:
                handler.send_text("error %s" % UNKNOWN_ERROR)

            logger.exception(UNKNOWN_ERROR)


class DeviceOperationMixIn(object):
    """
    DeviceOperationMixIn require implement methods:
        on_mainboard_message(self, watcher, revent)
        on_headboard_message(self, watcher, revent)
        clean(self)

    the 'clean' method will be invoked before mainboard/headboard be closed.
    """

    _cleaned = False
    _sock_mb = _sock_th = None
    _watcher_mb = _watcher_th = _watcher_timer = None

    def __init__(self, stack, handler):
        kernel = stack.loop.data
        kernel.exclusive(self)

        logger.info("Init %s task", self.__class__)
        self.stack = stack
        self.handler = handler

        try:
            tools.toolhead_power_off()

            logger.debug("Connect to mainboard %s", MAINBOARD_ENDPOINT)
            ms = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            ms.connect(MAINBOARD_ENDPOINT)
            ms.setblocking(False)

            logger.debug("Connect to headboard %s", HEADBOARD_ENDPOINT)
            hs = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            hs.connect(HEADBOARD_ENDPOINT)
            hs.setblocking(False)
        except socket.error as err:
            logger.exception("Connect to %s failed", MAINBOARD_ENDPOINT)
            self._disconnect()

            if err.args[0] in [ECONNREFUSED, ENOENT]:
                raise RuntimeError(SUBSYSTEM_ERROR, NO_RESPONSE)
            else:
                raise

        self._sock_mb = ms
        self._sock_th = hs

        logger.info("HAL connected")

        self._watcher_mb = self.stack.loop.io(ms, pyev.EV_READ,
                                              self.on_mainboard_message, ms)
        self._watcher_mb.start()

        self._watcher_th = self.stack.loop.io(hs, pyev.EV_READ,
                                              self.on_headboard_message, hs)
        self._watcher_th.start()

        self._watcher_timer = stack.loop.timer(1, 1, self.on_timer)
        self._watcher_timer.start()

    @property
    def label(self):
        return "%s@%s" % (self.handler.address, self.__class__.__name__)

    def _clean(self):
        try:
            if self._cleaned is False:
                self._cleaned = True
                self.clean()

                self._watcher_timer.stop()
                self._watcher_mb.stop()
                self._sock_mb.close()
                self._watcher_th.stop()
                self._sock_th.close()

            logger.debug("Clean device operation task")
        except Exception:
            logger.exception("Error while clean task '%s'", self.__class__)

    def on_exit(self):
        self._clean()
        kernel = self.stack.loop.data
        kernel.release_exclusive(self)

    def on_mainboard_message(self, watcher, revent):
        logger.warn("Recive message from mainboard but not handle: %s" %
                    watcher.data.recv(4096).decode("utf8", "ignore"))

    def on_headboard_message(self, watcher, revent):
        logger.warn("Recive message from headboard but not handle: %s" %
                    watcher.data.recv(4096).decode("utf8", "ignore"))

    def on_dead(self, reason=None):
        self._clean()
        self.handler.send_text("error KICKED")
        logger.info("%s dead (reason=%s)", self.__class__.__name__, reason)
        self.handler.close()

    def clean(self):
        pass

    def on_timer(self, watcher, revent):
        pass
