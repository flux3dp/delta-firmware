

class StartupMacro(object):
    def __init__(self, on_success_cb, on_error_cb):
        self._on_success_cb = on_success_cb
        self._on_error_cb = on_error_cb

    def start(self, executor):
        # Select extruder 0
        executor.main_ctrl.send_cmd("T0", executor)
        # Set units to mm
        executor.main_ctrl.send_cmd("G21", executor)
        # Absolute Positioning
        executor.main_ctrl.send_cmd("G90", executor)
        # Set E to 0
        executor.main_ctrl.send_cmd("G92E0", executor)
        # Home
        executor.main_ctrl.send_cmd("G28", executor)

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
