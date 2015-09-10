
from errno import ECONNREFUSED, ENOENT
import weakref
import logging
import socket

logger = logging.getLogger(__name__)

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.config import uart_config, DEBUG
from fluxmonitor.err_codes import NO_RESPONSE, UNKNOW_ERROR, RESOURCE_BUSY


class ExclusiveMixIn(object):
    def __init__(self, server, sender):
        self.server = server
        self.owner = weakref.ref(sender, self.on_dead)

    def on_message(self, message, sender):
        if self.owner() == sender:
            if isinstance(self, CommandMixIn):
                CommandMixIn.on_message(self, message, sender)
            else:
                self.on_owner_message(message, sender)
        else:
            if message.rstrip("\x00") == b"kick":
                self.owner().close("kicked")
                self.on_dead(self.owner, "Kicked")
                sender.send_text("ok")
            else:
                err = "error %s %s" % (RESOURCE_BUSY, self.__class__.__name__)
                sender.send_text(err.encode())

    def on_dead(self, sender_proxy, reason=None):
        if self.server.this_task != self:
            return

        if not reason:
            reason = "Connection/Owner gone"
        logger.info("%s abort (%s)" % (self.__class__.__name__, reason))
        self.server.exit_task(self, False)


class CommandMixIn(object):
    def on_message(self, buf, sender):
        try:
            cmd = buf.rstrip(b"\x00\n\r").decode("utf8", "ignore")

            if len(cmd) > 128:
                logger.error("Recive cmd length > 128, kick connection")
                sender.close()
                return

            if cmd == "position":
                sender.send_text(self.__class__.__name__)
            else:
                response = self.dispatch_cmd(cmd, sender)
                if response is not None:
                    sender.send_text(response)

        except RuntimeError as e:
            sender.send_text(("error %s" % e.args[0]).encode())
        except Exception as e:
            if DEBUG:
                sender.send_text("error %s %s" % (UNKNOW_ERROR, e))
            else:
                sender.send_text("error %s" % UNKNOW_ERROR)

            logger.exception(UNKNOW_ERROR)


class DeviceOperationMixIn(object):
    """
    DeviceOperationMixIn require implement methods:
        on_mainboard_message(self, sender)
        on_headboard_message(self, sender)
    And require `self.server` property
    """
    connected = False

    _uart_mb = _uart_hb = None
    _async_mb = _async_hb = None

    def connect(self, mainboard_only=False):
        try:
            self.connected = True
            self._uart_mb = mb = socket.socket(socket.AF_UNIX,
                                               socket.SOCK_STREAM)
            logger.info("Connect to mainboard %s" % uart_config["mainboard"])
            mb.connect(uart_config["mainboard"])
            self._async_mb = AsyncIO(mb, self.on_mainboard_message)
            self.server.add_read_event(self._async_mb)

            if not mainboard_only:
                self._uart_hb = hb = socket.socket(socket.AF_UNIX,
                                                   socket.SOCK_STREAM)
                self._async_hb = AsyncIO(hb, self.on_headboard_message)
                self.server.add_read_event(self._async_hb)
                logger.info("Connect to headboard %s" %
                            uart_config["headboard"])
                hb.connect(uart_config["headboard"])

        except socket.error as err:
            logger.exception("Connect to %s failed" % uart_config["mainboard"])
            self.disconnect()

            if err.args[0] in [ECONNREFUSED, ENOENT]:
                raise RuntimeError(NO_RESPONSE)
            else:
                raise

    def on_mainboard_message(self, sender):
        logger.warn("Recive message from mainboard but not handle: %s" %
                    sender.obj.recv(4096).decode("utf8", "ignore"))

    def on_headboard_message(self, sender):
        logger.warn("Recive message from headboard but not handle: %s" %
                    sender.obj.recv(4096).decode("utf8", "ignore"))

    def disconnect(self):
        if self._async_mb:
            self.server.remove_read_event(self._async_mb)
            self._async_mb = None

        if self._async_hb:
            self.server.remove_read_event(self._async_hb)
            self._async_hb = None

        if self._uart_mb:
            logger.info("Disconnect from mainboard")
            self._uart_mb.close()
            self._uart_mb = None

        if self._uart_hb:
            logger.info("Disconnect from headboard")
            self._uart_hb.close()
            self._uart_hb = None

        self.connected = False


class DeviceMessageReceiverMixIn(object):
    _mb_swap = _hb_swap = None

    def recv_from_mainboard(self, sender):
        buf = sender.obj.recv(4096)
        if self._mb_swap:
            self._mb_swap += buf.decode("ascii", "ignore")
        else:
            self._mb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._mb_swap)
        self._mb_swap = messages.pop()

        for msg in messages:
            yield msg

    def recv_from_headboard(self, sender):
        buf = sender.obj.recv(4096)
        if self._hb_swap:
            self._hb_swap += buf.decode("ascii", "ignore")
        else:
            self._hb_swap = buf.decode("ascii", "ignore")

        messages = re.split("\r\n|\n", self._hb_swap)
        self._hb_swap = messages.pop()

        for msg in messages:
            yield msg
