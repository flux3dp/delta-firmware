
from subprocess import Popen, PIPE
import fcntl
import os

from fluxmonitor.misc import read_all, AsyncRead

__all__ = ["call_and_return_0_or_die"]

def call_and_return_0_or_die(args):
    # As title (What you see what you get.)
    proc = Popen(args, stdout=PIPE, stderr=PIPE, stdin=PIPE)
    proc.stdin.close()

    stdout, stderr = read_all([proc.stdout, proc.stderr])
    proc.wait()
    if proc.poll() != 0:
        raise RuntimeError("Execute command %s failed: %s return %s" % (" ".join(args), stderr, proc.poll()))

    return stdout, stderr

class Process(Popen):
    def __init__(self, manager, cmd):
        self.cmd = " ".join(cmd)
        self.manager = manager

        super(Process, self).__init__(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)

        self._make_nonblock(self.stdout)
        self._make_nonblock(self.stderr)

        self.manager.rlist += [
            AsyncRead(self.stdout, self._on_stdout),
            AsyncRead(self.stderr, self._on_stderr)]

    def _make_nonblock(self, file_obj):
        fd = file_obj.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    def _on_stdout(self, sender):
        buf = sender.obj.read(4096)
        if buf: self.manager.logger.debug(buf)
        else: self._close(sender)

    def _on_stderr(self, sender):
        buf = sender.obj.read(4096)
        if buf: self.manager.logger.debug(buf)
        else: self._close(sender)

    def _close(self, sender):
        self.manager.rlist.remove(sender)

        if self.poll() != None:
            self.manager.on_daemon_closed(self)

    def __repr__(self):
        return "<Process: %s>" % self.cmd