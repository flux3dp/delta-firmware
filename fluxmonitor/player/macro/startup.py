
from .base import MacroBase


class StartupMacro(MacroBase):
    name = "STARTING"

    filament_detect = True

    def __init__(self, on_success_cb, options=None):
        self._on_success_cb = on_success_cb

        if options:
            self.filament_detect = options.filament_detect == "Y"

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

    def on_command_empty(self, k):
        self._on_success_cb()
