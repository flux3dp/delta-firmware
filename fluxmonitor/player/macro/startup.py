
from .base import MacroBase


class StartupMacro(MacroBase):
    name = "STARTING"

    filament_detect = True
    backlash_config = None

    def __init__(self, on_success_cb, options=None):
        self._on_success_cb = on_success_cb

        if options:
            self.filament_detect = options.filament_detect == "Y"
            self.backlash_config = options.backlash_config

    def start(self, k):
        # Select extruder 0
        k.mainboard.send_cmd("T0")
        # Absolute Positioning
        k.mainboard.send_cmd("G90")
        # Set E to 0
        k.mainboard.send_cmd("G92E0")
        # Home
        k.mainboard.send_cmd("G28+")

        if self.filament_detect:
            k.mainboard.send_cmd("X8O")
        else:
            k.mainboard.send_cmd("X8F")

        if self.backlash_config:
            k.mainboard.send_cmd("M711 A%(A).4f B%(B).4f C%(C).4f" %
                                 self.backlash_config)
        else:
            k.main_ctrl.send_cmd("M711 J0.5 K0.5 L0.5 A0 B0 C0")

    def giveup(self, k):
        pass

    def on_command_empty(self, k):
        self._on_success_cb()
