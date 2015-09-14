
from __future__ import absolute_import
import logging.config
import signal
import fcntl
import sys
import os

from fluxmonitor.config import general_config
from fluxmonitor.main import FluxMonitor


LOG_FORMAT = "[%(asctime)s,%(levelname)s,%(name)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def create_logger(options):
    log_format = general_config.get("log_syntax", LOG_FORMAT)
    log_datefmt = general_config.get("log_timefmt", LOG_DATEFMT)
    log_level = logging.DEBUG if options.debug else logging.INFO

    handlers = {}
    if sys.stdout.isatty():
        handlers['console'] = {
            'level': log_level,
            'formatter': 'default',
            'class': 'logging.StreamHandler',
        }

    if options.logfile:
        handlers['file'] = {
            'level': log_level,
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': options.logfile,
            'maxBytes': 5 * (2 ** 20),  # 10M
            'backupCount': 9
        }

    if options.debug:
        handlers['local_udp'] = {
            'level': log_level,
            'formatter': 'default',
            'class': 'fluxmonitor.diagnosis.log_helpers.DatagramHandler',
        }

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'default': {
                'format': log_format,
                'datefmt': log_datefmt
            }
        },
        'handlers': handlers,
        'loggers': {},
        'root': {
            'handlers': list(handlers.keys()),
            'level': 'DEBUG',
            'propagate': True
        }
    })


def deamon_entry(options, service=None):
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
            sys.stdout = open(os.devnull, 'r')
            sys.stderr = open(os.devnull, 'r')
            # sys.stdout = open(options.logfile, 'a')
            # sys.stderr = sys.stdout

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

    create_logger(options)
    server = FluxMonitor(options, service)

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

    try:
        if server.run() is False:
            return 1

    finally:
        if options.daemon:
            fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_UN)

        pid_handler.close()
        os.unlink(options.pidfile)


    return 0
