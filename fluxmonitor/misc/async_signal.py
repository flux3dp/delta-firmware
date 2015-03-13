
from errno import EAGAIN
from Queue import Queue
import fcntl
import os


def make_nonblock(fd):
    """make given fd nonblock"""

    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


def close_fds(*fds):
    """close all fd list in fds without raise exception"""

    for fd in fds:
        try:
            os.close(fd)
        except Exception:
            pass


def read_without_error(fd, size):
    """A read agent function

    return (True, str) when os.read return data
    return (False, None) when os.read raise `Resource empty` exception"""

    try:
        buf = os.read(fd, size)
        return True, buf
    except OSError as e:
        if e.errno is EAGAIN:
            return False, None
        else:
            raise e


class AsyncPipe(object):
    def __init__(self):
        self._fd_closed = False
        self._rfd, self._wfd = os.pipe()
        make_nonblock(self._rfd)

    def __del__(self):
        self.close()

    def fileno(self):
        if not self._fd_closed:
            return self._rfd

    def close(self):
        if not self._fd_closed:
            self._fd_closed = True
            close_fds(self._rfd, self._wfd)


class AsyncSignal(AsyncPipe):
    def __init__(self, callback=None):
        AsyncPipe.__init__(self)
        self.callback = callback

    def on_read(self, sender=None):
        success, buf = read_without_error(self._rfd, 1)
        if success and buf:
            # If read successed, trigger callback
            if self.callback:
                self.callback(self)

        elif success and not buf:
            # If fd has been closed
            self.close()
            raise RuntimeError("AsyncSignal has been closed")

    def send(self):
        os.write(self._wfd, b" ")


class AsyncQueue(Queue):
    def __init__(self, maxsize=0, callback=None):
        Queue.__init__(self, maxsize)
        self.callback = callback
        self._rfd, self._wfd = os.pipe()
        make_nonblock(self._rfd)

    def __del__(self):
        try:
            os.close(self._rfd)
        except Exception:
            pass

    def fileno(self):
        return self._rfd

    def on_read(self):
        if self.callback:
            self.callback(self)

    def put(self, item, block=True, timeout=None):
        Queue.put(self, item, block, timeout)
        os.write(self._wfd, b"\x00")

    def get(self, block=True, timeout=None):
        obj = Queue.get(self, block, timeout)

        try:
            # Clear signal IO
            os.read(self._rfd, 4096)
        except OSError as e:
            if e.errno is not EAGAIN:
                raise e

        return obj


class AsyncIO(object):
    def __init__(self, file_object, read_callback=None, write_callback=None):
        self.obj = file_object
        self.read_callback = read_callback
        self.write_callback = write_callback

    def fileno(self):
        return self.obj.fileno()

    def on_read(self):
        self.read_callback(self)

    def on_write(self):
        self.write_callback(self)
