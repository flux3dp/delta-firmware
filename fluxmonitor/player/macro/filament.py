
from .command import CommandMacro


class LoadFilamentMacro(CommandMacro):
    name = "LOAD_FILAMENT"

    def __init__(self, success_cb, index, detect, disable_accelerate=False, on_message=None):
        cmd = "C5" if "disable_accelerate" else "C3"
        if detect:
            cmd += "+"
        CommandMacro.__init__(self, success_cb, ("T%i" % index, cmd),
                              on_message)

    def giveup(self, k):
        k.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n", raw=1)


class UnloadFilamentMacro(CommandMacro):
    name = "UNLOAD_FILAMENT"

    def __init__(self, success_cb, index):
        CommandMacro.__init__(self, success_cb, ("T%i" % index, "C4"))
