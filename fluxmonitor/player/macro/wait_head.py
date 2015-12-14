

class WaitHeadMacro(object):
    name = "WAITING_HEAD"

    def __init__(self, on_success_cb, head_cmd):
        self._on_success_cb = on_success_cb
        self._head_cmd = head_cmd

    def start(self, executor):
        executor.head_ctrl.send_cmd(self._head_cmd, executor,
                                    allset_callback=self.allset)

    def allset(self, *args):
        self._on_success_cb()

    def giveup(self):
        pass

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
