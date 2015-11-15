
from subprocess import Popen, PIPE
from io import BytesIO
from time import time, sleep
import logging
import fcntl
import os

import pyev

__all__ = ["Process"]
logger = logging.getLogger(__name__)


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

    def __init__(self, service, cmd):
        self.cmd = " ".join(cmd)
        self.service = service

        super(Process, self).__init__(cmd, stdin=PIPE, stdout=PIPE,
                                      stderr=PIPE)

        self._make_nonblock(self.stdout)
        self._make_nonblock(self.stderr)

        self.stdout_watcher = self.service.loop.io(self.stdout, pyev.EV_READ,
                                                   self._on_stdout)
        self.stdout_watcher.start()
        self.stderr_watcher = self.service.loop.io(self.stderr, pyev.EV_READ,
                                                   self._on_stderr)
        self.stderr_watcher.start()

        self._closed = False

    def _make_nonblock(self, file_obj):
        fd = file_obj.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    def _on_stdout(self, watcher, revent):
        buf = self.stdout.read(4096)
        if buf:
            self.service.logger.debug(buf)
        else:
            watcher.stop()
            self.stdout_watcher = None
            self._close()

    def _on_stderr(self, watcher, revent):
        buf = self.stderr.read(4096)
        if buf:
            self.service.logger.debug(buf)
        else:
            watcher.stop()
            self.stderr_watcher = None
            self._close()

    def _close(self):
        try:
            if self.poll() is None:
                logger.warn("%s stdout closed but still alive." % self)
                self.kill()

            timeout = time() + 3.0
            while self.poll() is None:
                sleep(0.01)

            if self.poll() is None:
                logger.critical("%s became zombe." % self)
        except Exception:
            logger.exception("%s became zombe." % self)

        if not self._closed:
            # First _closed be invoked
            self._closed = True
            self.on_daemon_closed()

    def on_daemon_closed(self):
        self.service.on_daemon_closed(self)

    def __repr__(self):
        return "<Process: %s>" % self.cmd
