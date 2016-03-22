from __future__ import absolute_import

from logging.handlers import DatagramHandler as _DatagramHandler
import socket
import json
import sys


class DatagramHandler(_DatagramHandler):
    def __init__(self, host="255.255.255.255", port=7995):
        super(DatagramHandler, self).__init__(host, port)
        self.broadcast = (host == "255.255.255.255")

    def makePickle(self, record):
        """
        Pickles the record in binary format with a length prefix, and
        returns it ready for transmission across the socket.
        """
        ei = record.exc_info
        if ei:
            # just to get traceback text into record.exc_text ...
            dummy = self.format(record)
            record.exc_info = None  # to avoid Unpickleable error
        # See issue #14436: If msg or args are objects, they may not be
        # available on the receiving end. So we convert the msg % args
        # to a string, save it as msg and zap the args.
        d = dict(record.__dict__)
        d['msg'] = record.getMessage()
        d['args'] = None
        s = json.dumps(d)
        # s = cPickle.dumps(d, 1)
        if ei:
            record.exc_info = ei  # for next handler
        # slen = struct.pack(">L", len(s))
        return s

    def makeSocket(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.broadcast:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return s


def create_raven_logger(dsn):
    try:
        from fluxmonitor.storage import Metadata
        m = Metadata()
        import raven
        return {
            'level': 'ERROR',
            'class': 'raven.handlers.logging.SentryHandler',
            'machine': m.nickname.decode("utf8", "ignore"),
            'dsn': dsn
        }
    except ImportError:
        sys.stderr.write("Can not configure raven logger\n")
        sys.stderr.flush()
