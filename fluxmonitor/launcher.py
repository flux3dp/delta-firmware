
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
        pid_handler = os.open(options.pidfile,
                              os.O_CREAT | os.O_RDONLY | os.O_WRONLY, 0o644)
        fcntl.lockf(pid_handler, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(pid_handler, "w")
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


def load_service_klass(klass_name):
    module_name, klass_name = klass_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return module.__getattribute__(klass_name)


def init_service(klass_name, options):
    create_logger(options)
    service_klass = load_service_klass(klass_name)
    return service_klass(options)


def deamon_entry(options, service=None):
    pid_handler = None
    server = None
    pid = None

    # Close all file descriptor except stdin/stdout/stderr and pid file
    # descriptor
    os.closerange(3, 1024)

    if options.daemon:
        rfd, wfd = os.pipe()

        pid_t = os.fork()
        if pid_t == 0:
            # Second process
            os.close(rfd)
            os.setsid()
            pid_l = os.fork()
            if pid_l == 0:
                # Third process
                os.umask(0o27)

                try:
                    pid_handler = lock_pidfile(options)
                    pid = os.getpid()

                    pid_handler.write(repr(pid))
                    pid_handler.flush()

                    sys.stdin.close()
                    sys.stdout.close()
                    sys.stderr.close()

                    os.closerange(0, 3)

                    sys.stdin = open(os.devnull, 'r')
                    sys.stdout = open(os.devnull, 'w')
                    sys.stderr = open(os.devnull, 'w')

                    server = init_service(service, options)

                    os.write(wfd, b"\x00")
                except FatalException as e:
                    os.write(wfd, chr(e.args[0]))
                    return e.args[0]
                except Exception as e:
                    raise
                finally:
                    os.close(wfd)

            elif pid_l > 0:
                # Second process (fork success, do nothing)
                os.close(wfd)
                return 0
            else:
                # Second process (fork failed)
                sys.stderr.write('Fork failed\n')
                os.write(wfd, b"\x10")
                os.close(wfd)
                return 0x10

        elif pid_t > 0:
            # Main process
            os.close(wfd)
            flag = os.read(rfd, 4096)
            os.close(rfd)

            if flag == '':
                sys.stderr.write("Daemon no response\n")
                return 256

            else:
                if len(flag) > 1:
                    sys.stderr.write("%s\n" % flag[1:])
                return ord(flag[0])
        else:
            # Main process (fork failed)
            sys.stderr.write('Fork failed\n')
            return 0x10
    else:
        try:
            pid_handler = lock_pidfile(options)
            pid = os.getpid()
            pid_handler.write(repr(pid))
            pid_handler.flush()
        except FatalException as e:
            return e.args[0]

        server = init_service(service, options)


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
        if os.getpid() == pid:
            fcntl.lockf(pid_handler.fileno(), fcntl.LOCK_UN)
            pid_handler.close()
            os.unlink(options.pidfile)

    return 0


class FatalException(Exception):
    pass
