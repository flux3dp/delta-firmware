
from shlex import split as shlex_split

from .listener import UnixDgrmInterface


class PlayerUdpInterface(UnixDgrmInterface):
    def on_message(self, buf, endpoint):
        commands = shlex_split(buf)
        self.kernel.on_request(self, endpoint, *commands)
