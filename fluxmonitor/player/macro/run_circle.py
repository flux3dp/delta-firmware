
from math import sin, cos, pi
from .base import MacroBase

pi2 = pi * 2


class RunCircleMacro(MacroBase):
    name = "CORRECTING"

    def __init__(self, on_success_cb):
        self._on_success_cb = on_success_cb
        self.dir = 0  # 0 clockwise, 1 counterclockwise, 2 terminate
        self.step = pi / 60
        self.r = 0

    def giveup(self, k):
        self.direction = 0
        self.position = 0

    def feed(self, k):
        while not k.mainboard.queue_full and self.dir < 2:
            if self.r <= pi2 and self.r >= 0:
                x = sin(self.r) * 85.5
                y = -cos(self.r) * 85.5
                k.mainboard.send_cmd("G1 X%.2f Y%.2f" % (x, y))
                if self.dir == 0:
                    self.r += self.step
                elif self.dir == 1:
                    self.r -= self.step
            else:
                if self.dir == 0:
                    self.r = pi2
                    self.dir = 1
                elif self.dir == 1:
                    k.mainboard.send_cmd("G1 X0 Y0")
                    self.dir = 2

    def start(self, k):
        k.mainboard.send_cmd("G1 F6000 X0 Y0 Z3")
        self.feed(k)

    def on_command_empty(self, k):
        if self.dir == 2:
            self._on_success_cb()
        else:
            self.feed(k)

    def on_command_sendable(self, k):
        self.feed(k)
