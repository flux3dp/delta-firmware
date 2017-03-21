
from fluxmonitor.player.head_controller import exec_command
from .base import MacroBase


class WaitHeadMacro(MacroBase):
    name = "WAITING_HEAD"

    def __init__(self, on_success_cb):
        self._on_success_cb = on_success_cb

    def start(self, k):
        self.kernel = k
        k.mainboard.send_cmd("X5S72")

        self.send_cmd(k)
        k.toolhead.set_allset_callback(self.allset)

    def giveup(self, k):
        k.mainboard.send_cmd("X5S0")
        k.toolhead.set_allset_callback(None)

    def send_cmd(self, k):
        pass

    def allset(self, *args):
        if self.kernel.mainboard.ready:
            self.kernel.mainboard.send_cmd("X5S0")
            self._on_success_cb()


class ControlHeaterMacro(WaitHeadMacro):
    def __init__(self, on_success_cb, index, temperture):
        WaitHeadMacro.__init__(self, on_success_cb)
        self.arg = (index, temperture)

    def send_cmd(self, k):
        k.toolhead.ext.set_heater(self.arg[0], self.arg[1])


class ControlToolheadMacro(WaitHeadMacro):
    def __init__(self, on_success_cb, cmd):
        WaitHeadMacro.__init__(self, on_success_cb)
        self.cmd = cmd

    def send_cmd(self, k):
        exec_command(k.toolhead, self.cmd)
