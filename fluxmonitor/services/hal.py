
import logging

from fluxmonitor.hal.halservice import get_halservice
from fluxmonitor.interfaces.hal_internal import HalControlInterface
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

    def on_button_event(self, event):
        for client in self.internal_interface.clients:
            try:
                if client.alive:
                    client.send_event(event)
            except Exception:
                logger.exception("Error while sending button event")

    def reconnect(self):
        self.hal.reconnect()

    def reset_mainboard(self):
        self.hal.reset_mainboard()

    def toolhead_power_on(self):
        self.hal.toolhead_power_on()

    def toolhead_power_off(self):
        self.hal.toolhead_power_off()

    def toolhead_on(self):
        # 24V
        self.hal.toolhead_on()

    def toolhead_standby(self):
        self.hal.toolhead_standby()

    def diagnosis_mode(self):
        return self.hal.diagnosis_mode()

    def update_head_fw(self, callback):
        self.hal.update_head_fw(callback)

    def update_main_fw(self):
        self.hal.update_fw()

    def on_start(self):
        self.hal.start()
        self.internal_interface = HalControlInterface(self)
        logger.info("UART %s HAL selected", repr(self.hal.hal_name))
        self.watch_timer.start()

    def on_loop(self, watcher, revent):
        self.hal.on_loop()

    def on_shutdown(self):
        self.hal.close()
        self.watch_timer.stop()
