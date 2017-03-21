
from .base import MacroBase


class CommandMacro(MacroBase):
    name = "SCRIPT"

    def __init__(self, on_success_cb, commands=[], on_message_cb=None):
        self._on_success_cb = on_success_cb
        self._on_message_cb = on_message_cb
        self.commands = commands

    def start(self, k):
        for cmd in self.commands:
            k.mainboard.send_cmd(cmd)

    def on_command_empty(self, k):
        self._on_success_cb()

    def on_ctrl_message(self, k, data):
        if self._on_message_cb:
            self._on_message_cb(data)
