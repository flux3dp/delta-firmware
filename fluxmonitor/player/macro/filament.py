
from .command import CommandMacro


class LoadFilamentMacro(CommandMacro):
    name = "LOAD_FILAMENT"

    def __init__(self, success_cb, index, detect, on_message=None):
        CommandMacro.__init__(self, success_cb, ("T%i" % index,
                                                 "C3+" if detect else "C3"),
                              on_message)

    def giveup(self, k):
        k.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n", raw=1)


class UnloadFilamentMacro(CommandMacro):
    name = "UNLOAD_FILAMENT"

    def __init__(self, success_cb, index):
        CommandMacro.__init__(self, success_cb, ("T%i" % index, "C4"))
