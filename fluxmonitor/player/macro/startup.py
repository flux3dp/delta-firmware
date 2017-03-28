
from fluxmonitor.storage import Preference
from fluxmonitor.config import DEFAULT_H
from .base import MacroBase

M666_TEMPLATE = "M666X%(X).4fY%(Y).4fZ%(Z).4fR%(R).4fD%(D).5fH%(H).4f"
M711_TEMPLATE = "M711 A%(A).4f B%(B).4f C%(C).4f"


class StartupMacro(MacroBase):
    name = "STARTING"

    default_h = None
    filament_detect = True
    enable_backlash = False

    def __init__(self, on_success_cb, options=None):
        self._on_success_cb = on_success_cb

        self.default_h = DEFAULT_H

        if options:
            if options.correction in ("A", "H"):
                if options.zprobe_dist:
                    self.default_h = options.zprobe_dist
            elif options.head == "LASER":
                self.default_h = DEFAULT_H
            self.filament_detect = options.filament_detect
            self.enable_backlash = options.enable_backlash
            self.plus_extrusion = options.plus_extrusion

    def start(self, k):
        pref = Preference.instance()
        pref.plate_correction = {"H": self.default_h}

        # Apply M666
        k.mainboard.send_cmd(M666_TEMPLATE % pref.plate_correction)
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

        if self.enable_backlash:
            k.mainboard.send_cmd(M711_TEMPLATE % pref.backlash)
        else:
            k.mainboard.send_cmd("M711 J0.5 K0.5 L0.5 A0 B0 C0")

        if self.plus_extrusion:
            k.mainboard.send_cmd("M92E145")

    def giveup(self, k):
        pass

    def on_command_empty(self, k):
        self._on_success_cb()
