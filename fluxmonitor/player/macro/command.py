
class CommandMacro(object):
    name = "SCRIPT"

    def __init__(self, on_success_cb, commands=[], on_message_cb=None):
        self._on_success_cb = on_success_cb
        self._on_message_cb = on_message_cb
        self.commands = commands

    def start(self, executor):
        for cmd in self.commands:
            executor.main_ctrl.send_cmd(cmd, executor)

    def giveup(self):
        pass

    def on_command_empty(self, executor):
        self._on_success_cb()

    def on_command_sendable(self, executor):
        pass

    def on_mainboard_message(self, msg, executor):
        if self._on_message_cb:
            self._on_message_cb(msg)

    def on_headboard_message(self, msg, executor):
        pass

    def on_patrol(self, executor):
        pass
