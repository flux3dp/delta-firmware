
class MacroBase(object):
    def start(self, k):
        # Send any commands you want,
        # on_command_empty will be invoke when all yours commands are done.
        pass

    def giveup(self, k):
        # This method will be called if this macro has been interrupted.
        # 'start' method may be called again and restart using this macro.
        #
        # Return false ONLY when you send any commands into mainboard otherwise
        # player will get stuck.
        return True

    def on_command_empty(self, k):
        pass

    def on_command_sendable(self, k):
        pass

    def on_ctrl_message(self, k, data):
        # This method will be invoke when receive mainboard CTRL message,
        # CTRL message will put in data param.
        pass
