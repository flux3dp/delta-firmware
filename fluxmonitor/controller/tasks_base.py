
from errno import ECONNREFUSED
import weakref
import logging
import socket

logger = logging.getLogger(__name__)

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.config import uart_config
from fluxmonitor.err_codes import NO_RESPONSE


class ExclusiveTaskBase(object):
    def __init__(self, server, sender):
        self.server = server
        self.owner = weakref.ref(sender, self.on_dead)

    def on_dead(self, sender_proxy, reason=None):
        if not reason:
            reason = "Connection/Owner gone"
        logger.info("%s abort (%s)" % (self.__class__.__name__, reason))
        self.server.exit_task(False)


class DeviceOperationMixIn(object):
    """
    DeviceOperationMixIn require implement methods:
        on_mainboard_message(self, sender)
        on_headboard_message(self, sender)
    And require “self.server” property
    """
    connected = False

    _uart_mb = _uart_hb = None
    _async_mb = _async_hb = None

    def connect(self):
        try:
            self.connected = True
            self._uart_mb = mb = socket.socket(socket.AF_UNIX,
                                               socket.SOCK_STREAM)
            logger.info("Connect to mainboard %s" % uart_config["mainboard"])
            mb.connect(uart_config["mainboard"])
            self._async_mb = AsyncIO(mb, self.on_mainboard_message)
            self.server.add_read_event(self._async_mb)

            self._uart_hb = hb = socket.socket(socket.AF_UNIX,
                                               socket.SOCK_STREAM)
            self._async_hb = AsyncIO(hb, self.on_headboard_message)
            self.server.add_read_event(self._async_hb)
            logger.info("Connect to headboard %s" % uart_config["headboard"])
            hb.connect(uart_config["headboard"])

        except socket.error as err:
            logger.exception("Connect to %s failed" % uart_config["mainboard"])
            self.disconnect()

            if err.args[0] == ECONNREFUSED:
                raise RuntimeError(NO_RESPONSE)
            else:
                raise

    def disconnect(self):
        if self._async_mb:
            self.server.remove_read_event(self._async_mb)
            self._async_mb = None

        if self._async_hb:
            self.server.remove_read_event(self._async_hb)
            self._async_hb = None

        if self._uart_mb:
            logger.info("Disconnect to mainboard")
            self._uart_mb.close()
            self._uart_mb = None

        if self._uart_hb:
            logger.info("Disconnect to headboard")
            self._uart_hb.close()
            self._uart_hb = None

        self.connected = False
