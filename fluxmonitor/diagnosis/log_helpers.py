from __future__ import absolute_import

import logging.handlers
import sys


class RotatingFileHandler(logging.handlers.RotatingFileHandler):
    def emit(self, *args):
        super(RotatingFileHandler, self).emit(*args)
        self.flush()


def create_raven_logger(dsn):
    try:
        import fluxmonitor
        from fluxmonitor.storage import Metadata
        m = Metadata()
        import raven  # noqa
        return {
            'level': 'ERROR',
            'class': 'raven.handlers.logging.SentryHandler',
            'machine': m.nickname.decode("utf8", "ignore"),
            'release': fluxmonitor.__version__,
            'dsn': dsn
        }
    except ImportError:
        sys.stderr.write("Can not configure raven logger\n")
        sys.stderr.flush()
