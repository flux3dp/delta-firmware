

class StartupMacro(object):
    name = "STARTING"

    filament_detect = True
    backlash_config = None

    def __init__(self, on_success_cb, options=None):
        self._on_success_cb = on_success_cb

        if options:
            self.filament_detect = options.filament_detect == "Y"
            self.backlash_config = options.backlash_config

    def start(self, executor):
        # Select extruder 0
        executor.main_ctrl.send_cmd("T0", executor)
        # Absolute Positioning
        executor.main_ctrl.send_cmd("G90", executor)
        # Set E to 0
        executor.main_ctrl.send_cmd("G92E0", executor)
        # Home
        executor.main_ctrl.send_cmd("G28+", executor)

        if self.filament_detect:
            executor.main_ctrl.send_cmd("X8O", executor)
        else:
            executor.main_ctrl.send_cmd("X8F", executor)

        if self.backlash_config:
            executor.main_ctrl.send_cmd("M711 J0.5 K0.5 L0.5 "
                                        " A%(A).4f B%(B).4f C%(C).4f" %
                                        self.backlash_config, executor)
        else:
            executor.main_ctrl.send_cmd("M711 J0.5 K0.5 L0.5 A0 B0 C0", executor)

    def giveup(self):
        pass

    def on_command_empty(self, executor):
        self._on_success_cb()

    def on_command_sendable(self, executor):
        pass

    def on_mainboard_message(self, msg, executor):
        pass

    def on_headboard_message(self, msg, executor):
        pass

    def on_patrol(self, executor):
        pass
