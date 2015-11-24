
from errno import ECONNREFUSED, ENOENT
from shlex import split as shlex_split
import weakref
import logging
import socket
import re

import pyev

logger = logging.getLogger(__name__)

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.config import uart_config, DEBUG
from fluxmonitor.err_codes import NO_RESPONSE, UNKNOW_ERROR, RESOURCE_BUSY


# class ExclusiveMixIn(object):
#     def __init__(self, server, sender):
#         self.server = server
#         self.owner = weakref.ref(sender, self.on_dead)
#
#     def on_message(self, message, sender):
#         if self.owner() == sender:
#             if isinstance(self, CommandMixIn):
#                 CommandMixIn.on_message(self, message, sender)
#             else:
#                 self.on_owner_message(message, sender)
#         else:
#             if message.rstrip("\x00") == b"kick":
#                 self.owner().close("kicked")
#                 self.on_dead(self.owner, "Kicked")
#                 sender.send_text("ok")
#             else:
#                 err = "error %s %s" % (RESOURCE_BUSY, self.__class__.__name__)
#                 sender.send_text(err.encode())
#
#     def on_dead(self, sender_proxy, reason=None):
#         if self.server.this_task != self:
#             return
#
#         if not reason:
#             reason = "Connection/Owner gone"
#         logger.info("%s abort (%s)" % (self.__class__.__name__, reason))
#         self.server.exit_task(self, False)


class CommandMixIn(object):
    def on_text(self, buf, handler):
        try:
            cmd = buf.rstrip("\x00\n\r")

            if cmd == "position":
                handler.send_text(self.__class__.__name__)
            else:
                params = shlex_split(cmd)
                response = self.dispatch_cmd(handler, *params)
                if response is not None:
                    logger.error("Shoud not response anything")
                    handler.send_text(response)

        except RuntimeError as e:
            handler.send_text(("error %s" % e.args[0]).encode())
        except Exception as e:
            if DEBUG:
                handler.send_text("error %s %s" % (UNKNOW_ERROR, e))
            else:
                handler.send_text("error %s" % UNKNOW_ERROR)

            logger.exception(UNKNOW_ERROR)


class DeviceOperationMixIn(object):
    """
    DeviceOperationMixIn require implement methods:
        on_mainboard_message(self, watcher, revent)
        on_headboard_message(self, watcher, revent)
    And require `self.server` property
    """

    _uart_mb = _uart_hb = None
    _mb_watcher = _hb_watcher = None

    def __init__(self, stack, handler, enable_watcher=True):
        kernel = stack.loop.data
        kernel.exclusive(self)
        self.stack = stack
        self.handler = handler
        self._connect(enable_watcher)

    def on_exit(self, handler):
        kernel = self.stack.loop.data
        kernel.release_exclusive(self)
        self._disconnect()

    def _connect(self, enable_watcher):
        try:
            self._uart_mb = mb = socket.socket(socket.AF_UNIX,
                                               socket.SOCK_STREAM)
            logger.info("Connect to mainboard %s" % uart_config["mainboard"])
            mb.connect(uart_config["mainboard"])

            self._uart_hb = hb = socket.socket(socket.AF_UNIX,
                                               socket.SOCK_STREAM)
            logger.info("Connect to headboard %s" %
                        uart_config["headboard"])
            hb.connect(uart_config["headboard"])

            if enable_watcher:
                self._mb_watcher = self.stack.loop.io(
                    mb, pyev.EV_READ, self.on_mainboard_message, mb)
                self._mb_watcher.start()

                self._hb_watcher = self.stack.loop.io(
                    hb, pyev.EV_READ, self.on_headboard_message, hb)
                self._hb_watcher.start()

        except socket.error as err:
            logger.exception("Connect to %s failed" % uart_config["mainboard"])
            self._disconnect()

            if err.args[0] in [ECONNREFUSED, ENOENT]:
                raise RuntimeError(NO_RESPONSE)
            else:
                raise

    def on_mainboard_message(self, watcher, revent):
        logger.warn("Recive message from mainboard but not handle: %s" %
                    watcher.data.recv(4096).decode("utf8", "ignore"))

    def on_headboard_message(self, watcher, revent):
        logger.warn("Recive message from headboard but not handle: %s" %
                    watcher.data.recv(4096).decode("utf8", "ignore"))

    def _disconnect(self):
        if self._hb_watcher:
            self._hb_watcher.stop()
            self._hb_watcher = None

        if self._mb_watcher:
            self._mb_watcher.stop()
            self._mb_watcher = None

        if self._uart_mb:
            logger.info("Disconnect from mainboard")
            self._uart_mb.close()
            self._uart_mb = None

        if self._uart_hb:
            logger.info("Disconnect from headboard")
            self._uart_hb.close()
            self._uart_hb = None

    def go_to_hell(self):
        self.handler.close()

    def on_dead(self, sender_proxy, reason=None):
        if self.stack.this_task != self:
            return

        logger.info("%s abort (%s)" % (self.__class__.__name__, reason))
        self.stack.exit_task(self)


class DeviceMessageReceiverMixIn(object):
    _mb_swap = _hb_swap = None

    def recv_from_mainboard(self, buf):
        if self._mb_swap:
            self._mb_swap += buf.decode("ascii", "ignore")
        else:
            self._mb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._mb_swap)
        self._mb_swap = messages.pop()

        for msg in messages:
            yield msg

    def recv_from_headboard(self, buf):
        if self._hb_swap:
            self._hb_swap += buf.decode("ascii", "ignore")
        else:
            self._hb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._hb_swap)
        self._hb_swap = messages.pop()

        for msg in messages:
            yield msg


class ProtocolError(SystemError):
    pass
