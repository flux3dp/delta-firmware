
import logging

logger = logging.getLogger(__name__)

from fluxmonitor.hal.halservice import get_halservice
from .base import ServiceBase


class HalService(ServiceBase):
    def __init__(self, server):
        self.server = server
        super(HalService, self).__init__(server, logger)

        if server.options.manually:
            klass = get_halservice("manually")
        else:
            klass = get_halservice()

        self.hal = klass(server)
        logger.info("UART %s HAL selected" % self.hal.hal_name)

    def each_loop(self):
        pass

    def start(self):
        pass

    def shutdown(self):
        pass
