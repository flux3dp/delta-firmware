
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.hal.halservice import get_halservice
from .base import ServiceBase


class HalService(ServiceBase):
    POLL_TIMEOUT = 3.0

    def __init__(self, options):
        super(HalService, self).__init__(logger)
        self.options = options

        if options.manually:
            klass = get_halservice("manually")
        else:
            klass = get_halservice()

        self.hal = klass(self)
        logger.info("UART %s HAL selected" % self.hal.hal_name)

    def each_loop(self):
        pass

    def on_start(self):
        pass

    def on_shutdown(self):
        self.hal.close()
