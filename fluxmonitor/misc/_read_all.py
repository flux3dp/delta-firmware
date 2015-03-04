
import select
from time import time

try:
    from io import StringIO
except ImportError:
    from StringIO import StringIO

def read_all(fd, timeout=30.0):
    ra = ReadAll(fd)
    return ra.read(timeout)

class ReadAll(object):
    def __init__(self, fds):
        self.__rlist = [fd for fd in fds]
        self.__buffers = [StringIO() for fd in fds]

    def read(self, timeout=None):
        rlist = self.__rlist
        start_at = time()

        while rlist:
            if timeout != None and time() - start_at > timeout: raise RuntimeError("Timeout")

            rl, wl, xl = select.select(rlist, (), (), min(3., time() - start_at))
            for fd in rl:
                buf = fd.read()
                if buf:
                    self.__buffers[self.__rlist.index(fd)].write(buf.decode("utf8"))
                else:
                    rlist.remove(fd)

        return [b.getvalue() for b in self.__buffers]

    def get_fileno(self, obj):
        if isinstance(obj, int):
            return obj
        else:
            return obj.fileno()


if __name__ == "__main__":
    import subprocess
    proc = subprocess.Popen(["ls", "/"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = read_all([proc.stdout, proc.stderr])
    print("STDOUT: %s" % stdout)
    print("STDERR: %s" % stderr)

    proc = subprocess.Popen(["ls", "/werqwerqwer"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = read_all([proc.stdout, proc.stderr])
    print("STDOUT: %s" % stdout)
    print("STDERR: %s" % stderr)

    proc = subprocess.Popen(["sleep", "5"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = read_all([proc.stdout, proc.stderr], 2)

