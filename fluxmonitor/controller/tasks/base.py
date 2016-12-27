
from errno import ECONNREFUSED, ENOENT
from shlex import split as shlex_split
import logging
import socket

import pyev

from fluxmonitor.err_codes import SUBSYSTEM_ERROR, NO_RESPONSE, UNKNOWN_ERROR
from fluxmonitor.config import MAINBOARD_ENDPOINT, HEADBOARD_ENDPOINT, DEBUG

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
            self.close()

        except Exception as e:
            if DEBUG:
                handler.send_text("error %s %s" % (UNKNOWN_ERROR, e))
            else:
                handler.send_text("error %s" % UNKNOWN_ERROR)

            logger.exception(UNKNOWN_ERROR)


class DeviceOperationMixIn(object):
    __toolhead_delayoff_timer = None

    @classmethod
    def __close_delayoff_toolhead(cls, w=None, r=None):  # noqa
        if cls.__toolhead_delayoff_timer:
            timer_w = cls.__toolhead_delayoff_timer
            timer_w.stop()
            io_w = timer_w.data
            io_w.stop()
            logger.info("Close toolhead delayoff connection (fileno=%s)",
                        io_w.fd)
            sock = io_w.data
            sock.close()
            cls.__toolhead_delayoff_timer = None

    @classmethod
    def _set_delay_toolhead_off(cls, instance):
        if cls.__toolhead_delayoff_timer:
            logger.warning("Already exist a toolhead delayoff data")
            cls.__close_delayoff_toolhead()

        io_w = instance._hb_watcher
        logger.info("Set toolhead delayoff data (fileno=%s)", io_w.fd)
        io_w.data = instance._uart_hb
        io_w.callback = lambda w, r: w.data.recv(128)
        timer_w = instance.stack.loop.timer(
            300., 0, cls.__close_delayoff_toolhead, io_w)
        timer_w.start()

        cls.__toolhead_delayoff_timer = timer_w

    """
    DeviceOperationMixIn require implement methods:
        on_mainboard_message(self, watcher, revent)
        on_headboard_message(self, watcher, revent)
        clean(self)

    the 'clean' method will be invoked before mainboard/headboard be closed.
    """

    _cleaned = False
    _uart_mb = _uart_hb = None
    _mb_watcher = _hb_watcher = None

    def __init__(self, stack, handler, enable_watcher=True, mb_sock=None,
                 th_sock=None):
        kernel = stack.loop.data
        kernel.exclusive(self)
        self.stack = stack
        self.handler = handler
        self._connect(enable_watcher, mb_sock, th_sock)

    @property
    def label(self):
        return "%s@%s" % (self.handler.address, self.__class__.__name__)

    def _clean(self):
        try:
            if self._cleaned is False:
                self._cleaned = True
                self.clean()

            logger.debug("Clean device operation task")
        except Exception:
            logger.exception("Error while clean task '%s'", self.__class__)

    def on_exit(self):
        self._clean()
        kernel = self.stack.loop.data
        kernel.release_exclusive(self)
        self._disconnect()

    def deplay_toolhead_off(self):
        return False

    def _connect(self, enable_watcher, mb, hb):
        try:
            if not mb:
                mb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                logger.info("Connect to mainboard %s", MAINBOARD_ENDPOINT)
                mb.connect(MAINBOARD_ENDPOINT)
            self._uart_mb = mb

            if not hb:
                hb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                logger.info("Connect to headboard %s", HEADBOARD_ENDPOINT)
                hb.connect(HEADBOARD_ENDPOINT)
            self._uart_hb = hb

            if enable_watcher:
                self._mb_watcher = self.stack.loop.io(
                    mb, pyev.EV_READ, self.on_mainboard_message, mb)
                self._mb_watcher.start()

                self._hb_watcher = self.stack.loop.io(
                    hb, pyev.EV_READ, self.on_headboard_message, hb)
                self._hb_watcher.start()

        except socket.error as err:
            logger.exception("Connect to %s failed", MAINBOARD_ENDPOINT)
            self._disconnect()

            if err.args[0] in [ECONNREFUSED, ENOENT]:
                raise RuntimeError(SUBSYSTEM_ERROR, NO_RESPONSE)
            else:
                raise

    def _disconnect(self):
        if self._mb_watcher:
            logger.info("Disconnect from mainboard")
            self._mb_watcher.stop()
            self._uart_mb.close()
            self._mb_watcher = self._uart_mb = None

        if self._hb_watcher:
            if self.deplay_toolhead_off():
                try:
                    logger.info("Delay disconnect from toolhead")
                    self.__class__._set_delay_toolhead_off(self)
                    return
                except:
                    logger.exception("Set toolhead delay disconnect failed")
            logger.info("Disconnect from toolhead")
            self._hb_watcher.stop()
            self._uart_hb.close()
            self._hb_watcher = self._uart_hb = None

    def on_mainboard_message(self, watcher, revent):
        logger.warn("Recive message from mainboard but not handle: %s" %
                    watcher.data.recv(4096).decode("utf8", "ignore"))

    def on_headboard_message(self, watcher, revent):
        logger.warn("Recive message from headboard but not handle: %s" %
                    watcher.data.recv(4096).decode("utf8", "ignore"))

    def on_dead(self, reason=None):
        self._clean()
        self._disconnect()
        self.handler.send_text("error KICKED")
        logger.info("%s dead (reason=%s)", self.__class__.__name__, reason)
        self.handler.close()
