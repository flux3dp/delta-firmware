
from errno import EAGAIN, errorcode
from select import select
import fcntl
import os


def lock_pidfile(pidfile):
    try:
        pid_handler = os.open(pidfile,
                              os.O_CREAT | os.O_RDONLY | os.O_WRONLY, 0o644)
        select((), (pid_handler, ), (), 1.0)
        fcntl.lockf(pid_handler, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(pid_handler, "w")
    except IOError as e:
        if e.args[0] == EAGAIN:
            raise SystemError(0x80, 'Can not lock pidfile %s\n' % pidfile)
        else:
            raise SystemError(0x81, 'Can not open pidfile %s (%s)\n' % (
                              pidfile, errorcode.get(e.args[0], "?")))


def load_pid(pidfile):
    if os.path.exists(pidfile):
        pid_handler = os.open(pidfile, os.O_RDONLY | os.O_WRONLY, 0o644)
        try:
            fcntl.lockf(pid_handler, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
        except IOError as e:
            if e.args[0] == EAGAIN:
                with open(pidfile, "r") as f:
                    return int(f.read())
            else:
                raise
        finally:
            os.close(pid_handler)
    else:
        return None
