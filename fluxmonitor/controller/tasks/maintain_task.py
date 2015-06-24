
from .base import CommandMixIn, DeviceOperationMixIn


class MaintainTask(CommandMixIn, DeviceOperationMixIn):
    def __init__(self, server, sock):
        self.server = server
        self.connect()

    def __del__(self):
        self.disconnect()

    def make_mainboard_cmd(self, cmd):
        self._uart_mb.send(("%s\n" % cmd).encode())
        return self._uart_mb.recv(128).decode("ascii", "ignore").strip()

    def dispatch_cmd(self, cmd, sock):
        if cmd == "home":
            return self.make_mainboard_cmd("G28")
        elif cmd == "quit":
            self.disconnect()
            self.server.exit_task(self)
            return "ok"
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

