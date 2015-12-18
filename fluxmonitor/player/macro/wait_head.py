

class WaitHeadMacro(object):
    name = "WAITING_HEAD"

    def __init__(self, on_success_cb, head_cmd):
        self._on_success_cb = on_success_cb
        self._head_cmd = head_cmd

    def start(self, executor):
        self._ex = executor
        executor.main_ctrl.send_cmd("X5S72", executor)
        executor.head_ctrl.send_cmd(self._head_cmd, executor,
                                    allset_callback=self.allset)

    def allset(self, *args):
        self._ex.main_ctrl.send_cmd("X5S0", self._ex)
        self._on_success_cb()

    def giveup(self):
        self._ex.main_ctrl.send_cmd("X5S0", self._ex)

    def on_command_empty(self, executor):
        pass

    def on_command_sendable(self, executor):
        pass

    def on_mainboard_message(self, msg, executor):
        pass

    def on_headboard_message(self, msg, executor):
        pass

    def on_patrol(self, executor):
        pass
