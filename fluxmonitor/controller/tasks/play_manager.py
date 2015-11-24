
from subprocess import Popen, PIPE
from tempfile import mktemp
import logging
import socket
import fcntl
import os

import pyev

from fluxmonitor.config import PLAY_ENDPOINT
from fluxmonitor.err_codes import RESOURCE_BUSY

logger = logging.getLogger(__name__)


class PlayerManager(object):
    _sock = None

    def __init__(self, loop, taskfile):
        try:
            proc = Popen(["fluxplayer", "--task", taskfile], stdin=PIPE,
                         stdout=PIPE, stderr=PIPE)

            for io in (proc.stdout, proc.stderr):
                fd = io.fileno()
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            std_watcher = loop.io(proc.stdout, pyev.EV_READ, self.on_console,
                                  proc.stdout)
            std_watcher.start()
            err_watcher = loop.io(proc.stderr, pyev.EV_READ, self.on_console,
                                  proc.stderr)
            err_watcher.start()

            self.watchers = (std_watcher, err_watcher)
            self.proc = proc

        except Exception:
            raise

    def __del__(self):
        for w in self.watchers:
            self.watchers[0].stop()
            self.watchers[0].data = None
        self.watchers = None
        self.proc = None
        self._sock = None

    @property
    def sock(self):
        try:
            if not self._sock:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._sock.bind(mktemp())
                self._sock.connect(PLAY_ENDPOINT)
            return self._sock
        except socket.error:
            raise RuntimeError(RESOURCE_BUSY)

    def on_console(self, watcher, revent):
        buf = watcher.data.read(4096).strip()
        if buf:
            logger.getChild("CONSOLE").debug(buf)
        else:
            watcher.data.close()
            watcher.data = None
            watcher.stop()

    def pause(self):
        self.sock.send("PAUSE")
        return self.sock.recv(4096)

    def resume(self):
        self.sock.send("RESUME")
        return self.sock.recv(4096)

    def abort(self):
        self.sock.send("ABORT")
        return self.sock.recv(4096)

    # def load_filament(self):
    #     self.sock.send("LOAD_FILAMENT")
    #     return self.sock.recv(4096)
    #
    # def eject_filament(self):
    #     self.sock.send("EJECT_FILAMENT")
    #     return self.sock.recv(4096)

    def report(self):
        self.sock.send("REPORT")
        return self.sock.recv(4096)

    def is_alive(self):
        return self.proc.poll() == None

    def terminate(self):
        self.proc.kill()
