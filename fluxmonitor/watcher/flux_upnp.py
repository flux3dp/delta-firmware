
from itertools import chain
import logging
import socket
import json

logger = logging.getLogger(__name__)

from .base import WatcherBase
from ._network_helpers import NetworkMonitorMix

DEFAULT_PORT = 3310


CODE_DISCOVER = 0x00
CODE_RESPONSE_DISCOVER = 0x01


class UpnpWatcher(WatcherBase, NetworkMonitorMix):
    ipaddress = []
    sock = None

    def __init__(self, memcache):
        super(UpnpWatcher, self).__init__(logger, memcache)

    def _on_status_changed(self, status):
        """Overwrite _on_status_changed witch called by `NetworkMonitorMix`
        when network status changed
        """
        nested = [st.get('ipaddr', [])
                  for _, st in status.items()]
        ipaddress = list(chain(*nested))

        if self.ipaddress != ipaddress:
            self.ipaddress = ipaddress
            self.replace_upnp_sock()

    def replace_upnp_sock(self):
        self.try_close_upnp_sock()
        if self.ipaddress:
            try:
                self.sock = UpnpSocket(self)
                self.rlist.append(self.sock)
                self.logger.info("Upnp UP")
            except socket.error:
                self.logger.exception("")
                self.try_close_upnp_sock()
        else:
                self.logger.info("Upnp DOWN")

    def try_close_upnp_sock(self):
        if self.sock:
            if self.sock in self.rlist:
                self.rlist.remove(self.sock)
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

    def run(self):
        self.bootstrap_network_monitor(self.memcache)
        self.replace_upnp_sock()
        super(UpnpWatcher, self).run()

    def cmd_discover(self):
        """Return IP Address in array"""
        return {"code": CODE_RESPONSE_DISCOVER, "model": "flux3dp:1",
                "id": "0xffffffff", "ip": self.ipaddress}


class UpnpSocket(object):
    def __init__(self, server, port=DEFAULT_PORT):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", port))

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

        if payload.get('code') == CODE_DISCOVER:
            resp = json.dumps(self.server.cmd_discover())
            self.sock.sendto(resp, ("255.255.255.255", remote[1]))

    def close(self):
        self.sock.close()
