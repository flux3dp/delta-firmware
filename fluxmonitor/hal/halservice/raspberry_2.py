
from RPi import GPIO
import logging

from fluxmonitor.misc.systime import systime as time
from .base import BaseOnSerial
from .raspberry_1 import RPiUartHal, GPIOControlShared

logger = logging.getLogger("halservice.rasp2")

GPIO_V24_PIN = 15
V24_ON = GPIO.HIGH
V24_OFF = GPIO.LOW


class GPIOControl(GPIOControlShared):
    _v24_stat = V24_OFF

    def init_gpio_control_extend(self):
        GPIO.setup(GPIO_V24_PIN, GPIO.OUT, initial=V24_OFF)

    @property
    def v24_power(self):
        return self._v24_stat == V24_ON

    @v24_power.setter
    def v24_power(self, val):
        if val:
            if self._v24_stat != V24_ON:
                self._v24_stat = V24_ON
                GPIO.output(GPIO_V24_PIN, V24_ON)
                logger.debug("24v On")
        else:
            if self._v24_stat != V24_OFF:
                self._v24_stat = V24_OFF
                GPIO.output(GPIO_V24_PIN, V24_OFF)
                logger.debug("24v Off")

    def update_head_gpio(self):
        if len(self.headboard_watchers) > 0:
            if self.head_enabled is False:
                self.head_enabled = self.toolhead_power = True
        else:
            if self.head_enabled is True:
                self.v24_power = False
                self.head_enabled = False
                logger.debug("Head Power delay off")
                self._head_power_timer = time()


class UartHal(RPiUartHal, BaseOnSerial, GPIOControl):
    hal_name = "raspberrypi-2"

    def on_recvfrom_headboard(self, watcher, revent):
        if self.v24_power is False:
            self.v24_power = True
        super(UartHal, self).on_recvfrom_headboard(watcher, revent)
