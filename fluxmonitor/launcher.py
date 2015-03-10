
from __future__ import absolute_import

import logging
import signal
import fcntl
import sys
import os

from fluxmonitor.main import FluxMonitor

# TODO: temp make logger
console = logging.StreamHandler()
LOG_FORMAT = '%(name)-12s: %(levelname)-8s %(message)s'
console.setFormatter(logging.Formatter(LOG_FORMAT))
console.setLevel(logging.DEBUG)
logger = logging.getLogger('')
logger.setLevel(logging.DEBUG)
logger.addHandler(console)


def main(options):
    pid_handler = open(options.pidfile, 'w', 0)

    try:
        fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        sys.stderr.write('Can not start daemon, daemon maybe already running '
                         'in somewhere?\n')
        raise

    if options.daemon:
        pid_handler.close()
        pid_t = os.fork()
        if pid_t == 0:
            os.setsid()
            os.umask(0o27)

            sys.stdin.close()
            sys.stdout.close()
            sys.stderr.close()

            os.closerange(0, 1024)

            sys.stdin = open(os.devnull, 'r')
            if options.debug:
                sys.stdout = open('tmp/fluxmonitor.stdout.log', 'w')
                sys.stderr = open('tmp/fluxmonitor.stderr.log', 'w')
            else:
                sys.stdout = open(os.devnull, 'w')
                sys.stderr = open(os.devnull, 'w')

            pid_handler = open(options.pidfile, 'w', 0)
            pid_handler.write(repr(os.getpid()))
            pid_handler.flush()
            fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif pid_t > 0:
            return 0
        else:
            sys.stderr.write('Fork failed, fluxmonitord dead~\n')
            return 0x10
    else:
        pid_handler.write(repr(os.getpid()))

    server = FluxMonitor()

    def sigDbTerm(watcher, revent):
        sys.stdout.write("\n")
        server.kill(log="Recive SIGTERM/SIGINT")

    def sigTerm(watcher, revent):
        sys.stderr.write("\n")
        server.shutdown(log="Recive SIGTERM/SIGINT")

    def sigUSRn(signum, frame):
        server.user_signal(signum)

    if hasattr(server, "user_signal"):
        signal.signal(signal.SIGUSR1, sigUSRn)
        signal.signal(signal.SIGUSR2, sigUSRn)

    if server.start() is False:
        return 1

    # term_watcher = server.loop.signal(signal.SIGTERM, sigTerm)
    # term_watcher.start()
    # itrup_wathcer = server.loop.signal(signal.SIGINT, sigTerm)
    # itrup_wathcer.start()

    if options.shell:
        import IPython
        IPython.embed()
        server.shutdown(log="Abort from shell, press ctrl+c will kill the "
                        "server directly")
        signal.signal(signal.SIGTERM, sigDbTerm)
        signal.signal(signal.SIGINT, sigDbTerm)
    else:
        signal.signal(signal.SIGTERM, sigTerm)
        signal.signal(signal.SIGINT, sigTerm)

    while server.isAlive():
        server.join(3.0)

    if options.daemon:
        fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_UN)
        pid_handler.close()
        try:
            os.unlink(options.pidfile)
        except Exception:
            pass

    return 0
