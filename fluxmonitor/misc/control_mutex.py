
from signal import SIGTERM, SIGKILL
from errno import EAGAIN
import fcntl
import os

from fluxmonitor.storage import Storage

_PIDFILE = None

def pidfile():
    global _PIDFILE
    if not _PIDFILE:
        s = Storage()
        _PIDFILE = s.get_path("control.pid")
    return _PIDFILE


def locking_status():
    """
    return [pid]

    Return control program when pid and label, if no program is running, return
    0
    """

    fn = pidfile()
    if os.path.isfile(fn):
        try:
            with open(fn, "a+") as f:
                fcntl.lockf(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.lockf(f.fileno(), fcntl.LOCK_UN)

                with open(fn, "r" as f):
                    # Double check if process is alive
                    return psutil.pid_exists(int(f.read()))
                return 0
        except IOError:
            with open(fn, "r") as f:
                pid = int(f.read())
                return pid
        except ValueError:
            return 0
    else:
        return 0


def terminate(kill=False):
    pid = locking_status()
    if pid:
        if kill:
            os.kill(pid, SIGKILL)
        else:
            os.kill(pid, SIGTERM)
        return True
    return False
