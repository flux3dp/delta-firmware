
from __future__ import absolute_import
from errno import EAGAIN, errorcode
import logging.config
import importlib
import signal
import fcntl
import sys
import os

from fluxmonitor.config import general_config


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


def lock_pidfile(options):
    try:
        if os.path.exists(options.pidfile):
            old_pid_handler = open(options.pidfile, 'a+')
            dup_fd = os.dup(old_pid_handler.fileno())
            fcntl.lockf(dup_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pid_handler = os.fdopen(dup_fd, 'w', 0)
        else:
            pid_handler = open(options.pidfile, 'w', 0)
            fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        return pid_handler
    except IOError as e:
        if options.debug:
            raise
        elif e.args[0] == EAGAIN:
            sys.stderr.write('Can not lock pidfile %s\n' % options.pidfile)
            raise FatalException(0x80)
        else:
            sys.stderr.write('Can not open pidfile %s (%s)\n' %
                             (options.pidfile, errorcode.get(e.args[0], "?")))
            raise FatalException(0x81)


def close_fd():
    # Close all file descriptor except stdin/stdout/stderr and pid file
    # descriptor
    os.closerange(4, 1024)


def load_service_klass(klass_name):
    module_name, klass_name = klass_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return module.__getattribute__(klass_name)


def deamon_entry(options, service=None):
    close_fd()

    try:
        pid_handler = lock_pidfile(options)
        create_logger(options)
        service_klass = load_service_klass(service)
        server = service_klass(options)

    except FatalException as e:
        return e.args[0]

    if options.daemon:
        pid_t = os.fork()
        if pid_t == 0:
            os.setsid()
            os.umask(0o27)

            sys.stdin.close()
            sys.stdout.close()
            sys.stderr.close()

            sys.stdin = open(os.devnull, 'r')
            sys.stdout = open(os.devnull, 'r')
            sys.stderr = open(os.devnull, 'r')

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
        fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_UN)
        pid_handler.close()
        os.unlink(options.pidfile)


    return 0


class FatalException(Exception):
    pass
