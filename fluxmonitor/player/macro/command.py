
from .base import MacroBase


class ExecCommandMacro(MacroBase):
    _exec_commands = None

    def __init__(self, name, commands=[], restart_from_beginning=False,
                 prevent_pause=False):
        self.name = name
        self.prevent_pause = prevent_pause
        self.commands = commands
        self._from_beggining = restart_from_beginning

        if self._from_beggining is False:
            self._exec_commands = list(commands)

    def start(self, k):
        if self._from_beggining:
            self._exec_commands = list(self.commands)

        if self._exec_commands:
            if k.mainboard.buffered_cmd_size == 0:
                self.on_command_empty(k)
            # self.on_command_sendable(k)
        else:
            self._on_success()

    def on_command_sendable(self, k):
        pass
        # while not k.mainboard.queue_full:
        #     if self._exec_commands:
        #         cmd = self._exec_commands.pop(0)
        #         k.mainboard.send_cmd(cmd)
        #     else:
        #         return

    def on_command_empty(self, k):
        if self._exec_commands:
            cmd = self._exec_commands.pop(0)
            k.mainboard.send_cmd(cmd)
        else:
            self._on_success()
        # if self._exec_commands:
        #     self.on_command_sendable(k)
        # else:
        #     self._on_success()


class CommandMacro(ExecCommandMacro):
    # WARNING!: Old API
    name = "SCRIPT"

    def __init__(self, on_success_cb, commands=[], on_message_cb=None):
        super(CommandMacro, self).__init__(self.name, commands)
        self._on_success_cb = on_success_cb
        self._on_message_cb = on_message_cb

    def on_ctrl_message(self, k, data):
        if self._on_message_cb:
            self._on_message_cb(data)
