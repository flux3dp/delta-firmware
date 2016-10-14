
import logging

from fluxmonitor.hal.halservice import get_halservice
from .base import ServiceBase

logger = logging.getLogger(__name__)


class HalService(ServiceBase):
    def __init__(self, options):
        super(HalService, self).__init__(logger)
        self.options = options

        if options.manually:
            klass = get_halservice("manually")
        else:
            klass = get_halservice()

        self.hal = klass(self)
        self.watch_timer = self.loop.timer(5, 5, self.on_loop)

    def on_start(self):
        self.hal.start()
        logger.info("UART %s HAL selected", repr(self.hal.hal_name))
        self.watch_timer.start()

    def on_loop(self, watcher, revent):
        self.hal.on_loop()

    def on_shutdown(self):
        self.hal.close()
        self.watch_timer.stop()
