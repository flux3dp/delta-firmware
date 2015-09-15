
from signal import SIGTERM, SIGKILL
from errno import EAGAIN
import fcntl
import os

from fluxmonitor.config import general_config

"""
control_mutex use file lock to prevent two program run at sametime
"""


def _get_control_file():
    return os.path.join(general_config["db"], "control.pid")


def locking_status():
    """
    return [pid, label]

    Return control program when pid and label, if no program is running, return
    [0, None]
    """

    fn = _get_control_file()
    if os.path.isfile(fn):
        try:
            with open(fn, "a+") as f:
                fcntl.lockf(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.lockf(f.fileno(), fcntl.LOCK_UN)
                return 0, None
        except IOError:
            with open(fn, "r") as f:
                pid, label = f.read().split("\n", 1)
                return int(pid, 10), label.strip()
    else:
        return 0, None


def terminate(kill=False):
    pid, label = locking_status()
    if pid:
        if kill:
            os.kill(pid, SIGKILL)
        else:
            os.kill(pid, SIGTERM)
        return label
    return None


class ControlLock(object):
    def __init__(self, program_label):
        self.label = program_label
        self.mutex_file = _get_control_file()

    def lock(self):
        self.f = f = open(self.mutex_file, 'w')
        try:
            fcntl.lockf(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError as e:
            if e.args[0] == EAGAIN:
                raise RuntimeError("Another control program is running")
            else:
                raise

        f.write("%i\n%s\n" % (os.getpid(), self.label))
        f.flush()

    def unlock(self):
        fcntl.lockf(self.f.fileno(), fcntl.LOCK_UN)
        self.f.close()
        os.unlink(self.mutex_file)

    def __enter__(self):
        self.lock()
        return self

    def __exit__(self, type, value, traceback):
        self.unlock()
