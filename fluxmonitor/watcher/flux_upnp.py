
from itertools import chain
import logging
import socket
import struct
import json

logger = logging.getLogger(__name__)

from fluxmonitor.sys.net.monitor import Monitor
from .base import WatcherBase

DEFAULT_ADDR = "239.255.255.250"
DEFAULT_PORT = 3310


class UpnpWatcher(WatcherBase):
    def __init__(self, memcache):
        super(UpnpWatcher, self).__init__(logger, memcache)
        self.sock = UpnpSocket(self)
        self.nw_monitor = Monitor(None)

    def run(self):
        self.rlist.append(self.sock)
        super(UpnpWatcher, self).run()

    def cmd_discover(self):
        """Return IP Address in array"""
        nested = [st.get('ipaddr', [])
                  for _, st in self.nw_monitor.full_status().items()]
        return {"model": "flux3dp:1", "id": "0xffffffff",
                "ip": list(chain(*nested))}


class UpnpSocket(object):
    def __init__(self, server, addr=DEFAULT_ADDR, port=DEFAULT_PORT):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                             socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))

        mreq = struct.pack("4sl", socket.inet_aton(addr), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self.sock = sock
        self.server = server

    def fileno(self):
        return self.sock.fileno()

    def on_read(self):
        buf, remote = self.sock.recvfrom(1024)
        try:
            payload = json.loads(buf)

        except ValueError:
            logger.debug("Parse json error: %s" % buf)
            return

        if payload.get('request') == 'discover':
            resp = json.dumps(self.server.cmd_discover())
            self.sock.sendto(resp, remote)
