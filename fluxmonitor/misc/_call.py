
from subprocess import PIPE, call, Popen
from fluxmonitor.misc import read_all

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

