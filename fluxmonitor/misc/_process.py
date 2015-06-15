
from subprocess import Popen, PIPE
from io import BytesIO
from time import time
import fcntl
import os

from fluxmonitor.misc import AsyncIO

__all__ = ["Process"]


class Process(Popen):
    @staticmethod
    def call_with_output(*args):
        proc = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        buffer = BytesIO()
        ttl = time() + 15.0

        try:
            while ttl > time():
                l = buffer.write(proc.stdout.read())
                if l == 0:
                    break

            return buffer.getvalue()
        finally:
            if proc.poll() is None:
                proc.kill()

    def __init__(self, manager, cmd):
        self.cmd = " ".join(cmd)
        self.manager = manager

        super(Process, self).__init__(cmd, stdin=PIPE, stdout=PIPE,
                                      stderr=PIPE)

        self._make_nonblock(self.stdout)
        self._make_nonblock(self.stderr)

        self.manager.server.add_read_event(
            AsyncIO(self.stdout, self._on_stdout))
        self.manager.server.add_read_event(
            AsyncIO(self.stderr, self._on_stderr))

        self._closed = False

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
        self.manager.server.remove_read_event(sender)

        if not self._closed and self.poll() is not None:
            self._closed = True
            self.manager.on_daemon_closed(self)

    def __repr__(self):
        return "<Process: %s>" % self.cmd
