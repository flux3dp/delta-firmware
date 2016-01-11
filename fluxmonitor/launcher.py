
from __future__ import absolute_import
import logging.config
import importlib
import signal
import fcntl
import sys
import os

from fluxmonitor.misc.pidfile import lock_pidfile as _lock_pidfile
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

    if os.path.exists("/etc/raven.dsn"):
        from fluxmonitor.diagnosis.log_helpers import create_raven_logger
        with open("/etc/raven.dsn", "r") as f:
            dsn = f.read()
            handlers['raven'] = create_raven_logger(dsn)

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
            'level': log_level,
            'propagate': True
        }
    })


def lock_pidfile(options):
    try:
        return _lock_pidfile(options.pidfile, options.debug)
    except SystemError as e:
        sys.stderr.write(e.args[1])
        raise FatalException(e.args[0])


def load_service_klass(klass_name):
    module_name, klass_name = klass_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return module.__getattribute__(klass_name)


def init_service(klass_name, options):
    create_logger(options)

    if options.signal_debug:
        import pyev
        pyev.default_loop(pyev.EVFLAG_NOSIGMASK)

    service_klass = load_service_klass(klass_name)
    return service_klass(options)


def bind_signal(server, debug):
    if debug:
        def sigTerm(sig, frame):
            sys.stderr.write("\n")
            server.shutdown(log="Recive SIGTERM/SIGINT")

        signal.signal(signal.SIGTERM, sigTerm)
        signal.signal(signal.SIGINT, sigTerm)

        import traceback

        def sigUSR2(sig, frame):
            for l in traceback.format_stack():
                server.logger.error(l.rstrip())

        signal.signal(signal.SIGUSR2, sigUSR2)

    else:
        def sigTerm(watcher, revent):
            sys.stderr.write("\n")
            server.shutdown(log="Recive SIGTERM/SIGINT")

        watcher1 = server.loop.signal(signal.SIGTERM, sigTerm)
        watcher1.start()
        watcher2 = server.loop.signal(signal.SIGINT, sigTerm)
        watcher2.start()
        return (watcher1, watcher2)


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

    def sigTerm(sig, frame):
        sys.stderr.write("\n")
        server.shutdown(log="Recive SIGTERM/SIGINT")

    dummy = bind_signal(server, options.signal_debug)  # NOQA

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
