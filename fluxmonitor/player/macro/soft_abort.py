
from .base import MacroBase


class SoftAbort(MacroBase):
    name = "ABORTING"
    sent = False

    def on_command_empty(self, k):
        if self.sent:
            k.abort()
        else:
            k.mainboard.send_cmd("G91")
            k.mainboard.send_cmd("G1F6000E-40")
            k.mainboard.send_cmd("G90")
            self.sent = True
