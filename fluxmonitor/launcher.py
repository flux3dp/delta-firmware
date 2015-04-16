
from __future__ import absolute_import

import logging
import signal
import fcntl
import sys
import os

from fluxmonitor.config import general_config
from fluxmonitor.main import FluxMonitor


def create_argument_parser(proc_name, parser):
    parser.add_argument('--daemon', dest='daemon', action='store_const',
                        const=True, default=False, help='Run as daemon')
    parser.add_argument('--stop', dest='stop_daemon', action='store_const',
                        const=True, default=False, help='Stop daemon')
    parser.add_argument('--pid', dest='pidfile', type=str,
                        default='%s.pid' % proc_name, help='PID file')
    parser.add_argument('--debug', dest='debug', action='store_const',
                        const=True, default=False, help='Enable debug')


def create_logger():
    LOG_TIMEFMT = general_config["log_timefmt"]
    LOG_FORMAT = general_config["log_syntax"]

    logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_TIMEFMT)

    logger = logging.getLogger('')
    if general_config.get("debug"):
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)


def main(options, module=None):
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

            logfilebase = os.path.join(general_config["logfile"],
                                       module.__name__)

            sys.stdout = open("%s.log" % logfilebase, 'w')
            sys.stderr = open("%s.err.log" % logfilebase, 'w')

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
    server = FluxMonitor(module=module)

    def sigTerm(watcher, revent):
        sys.stderr.write("\n")
        server.shutdown(log="Recive SIGTERM/SIGINT")

    def sigUSRn(signum, frame):
        server.user_signal(signum)

    if hasattr(server, "user_signal"):
        signal.signal(signal.SIGUSR1, sigUSRn)
        signal.signal(signal.SIGUSR2, sigUSRn)

    signal.signal(signal.SIGTERM, sigTerm)
    signal.signal(signal.SIGINT, sigTerm)

    if server.run() is False:
        return 1

    if options.daemon:
        fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_UN)
        pid_handler.close()
        try:
            os.unlink(options.pidfile)
        except Exception:
            pass

    return 0
