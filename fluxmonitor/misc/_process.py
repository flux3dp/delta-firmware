
from subprocess import Popen, PIPE
import fcntl
import os

from fluxmonitor.misc import read_all, AsyncIO

__all__ = ["Process"]


class Process(Popen):
    def __init__(self, manager, cmd):
        self.cmd = " ".join(cmd)
        self.manager = manager

        super(Process, self).__init__(cmd, stdin=PIPE, stdout=PIPE,
                                      stderr=PIPE)

        self._make_nonblock(self.stdout)
        self._make_nonblock(self.stderr)

        self.manager.rlist += [
            AsyncIO(self.stdout, self._on_stdout),
            AsyncIO(self.stderr, self._on_stderr)]

    def _make_nonblock(self, file_obj):
        fd = file_obj.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    def _on_stdout(self, sender):
        buf = sender.obj.read(4096)
        if buf:
            self.manager.logger.debug(buf)
        else:
            self._close(sender)

    def _on_stderr(self, sender):
        buf = sender.obj.read(4096)
        if buf:
            self.manager.logger.debug(buf)
        else:
            self._close(sender)

    def _close(self, sender):
        self.manager.rlist.remove(sender)

        if self.poll() is not None:
            self.manager.on_daemon_closed(self)

    def __repr__(self):
        return "<Process: %s>" % self.cmd
