
from __future__ import absolute_import

import logging
import signal
import fcntl
import sys
import os

from fluxmonitor.config import general_config
from fluxmonitor.main import FluxMonitor


def create_logger():
    LOG_TIMEFMT = general_config["log_timefmt"]
    LOG_FORMAT = general_config["log_syntax"]

    logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_TIMEFMT)

    logger = logging.getLogger('')
    if general_config.get("debug"):
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    f = open(general_config["logfile"], "a")
    filelogger = logging.StreamHandler(stream=f)

    logger.addHandler(filelogger)


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

    create_logger()
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
