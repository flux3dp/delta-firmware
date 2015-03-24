
import logging

logger = logging.getLogger(__name__)

from serial import Serial

from fluxmonitor.config import serial_config
from fluxmonitor.misc.async_signal import AsyncIO
from .base import WatcherBase


class SerialCommunication(WatcherBase):
    def __init__(self, memcache):
        super(SerialCommunication, self).__init__(logger, memcache)
        logger.error("SerialCommunication")
        self._prepare_serial()

    def _prepare_serial(self):
        baud = serial_config["baudrate"]
        self.serial = Serial(port=serial_config["port"], timeout=0.25)
        if baud:
            self.serial.baudrate = baud
        self.rlist.append(AsyncIO(self.serial, self._on_serial_message))

    def _on_serial_message(self, sender):
        cmd = self.serial.readline()
        self.serial.write("flux %s\r\n" % cmd)
