
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.watcher.base import WatcherBase
from fluxmonitor.hal.uart import get_uart_hal


class HalUartWatcher(WatcherBase):
    def __init__(self, server):
        self.server = server
        super(HalUartWatcher, self).__init__(server, logger)

        if server.options.smoothie:
            klass = get_uart_hal("smoothie")
        else:
            klass = get_uart_hal()

        self.hal = klass(server)
        logger.info("UART %s HAL selected" % self.hal.hal_name)

    def each_loop(self):
        pass

    def start(self):
        pass

    def shutdown(self):
        pass
