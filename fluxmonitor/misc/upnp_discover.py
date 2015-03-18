
from time import time, sleep
import logging
import select
import socket
import json

logger = logging.getLogger(__name__)


from fluxmonitor.watcher.flux_upnp import DEFAULT_ADDR, DEFAULT_PORT


"""Discover Flux 3D Printer

Here is a simple example:

from fluxmonitor.misc.upnp_discover import UpnpDiscover

def my_callback(discover, model, id, ipaddss):
    print("Find Printer at: " + ipaddrs)

    # We find only one printer in this example
    discover.stop()


d = UpnpDiscover()
d.discover(my_callback)
"""


class UpnpDiscover(object):
    _last_sent = 0
    _break = True

    def __init__(self, addr=DEFAULT_ADDR, port=DEFAULT_PORT):
        self.addr = addr
        self.port = port

    def discover(self, callback, timeout=3.0):
        """
        Call this method to execute discover task

        @callback: when find a flux printer, it will invoke
        `callback(instance, model, id, ipaddrs)` where ipaddrs is a list.
        """
        self._break = False
        timeout_at = time() + timeout

        found = {}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                             socket.IPPROTO_UDP)

        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            while not self._break:
                self._send_request(sock)
                self._recv_response(sock, found, callback)
                self._sleep_or_quit(timeout_at)

        finally:
            sock.close()

    def stop(self):
        """Call this function to break discover task"""
        self._break = True

    def _send_request(self, sock):
        now = time()

        if now - self._last_sent > 0.1:
            sock.sendto(json.dumps({"request": "discover"}),
                        (self.addr, self.port))
            _last_sent = time()

    def _recv_response(self, sock, found, callback):
        while self._has_response(sock):
            if self._break:
                return

            buf, remote = sock.recvfrom(4096)
            payload = json.loads(buf)
            unique_id = payload.get("id")
            if unique_id in found and found[unique_id] == payload:
                # already found and does not has any update
                continue

            found[unique_id] = payload
            callback(self, payload.get("model"), unique_id,
                     payload.get("ip"))

    def _sleep_or_quit(self, timeout_at):
        time_left = timeout_at - time()
        if time_left > 0:
            sleep(min(time_left, 0.025))
        else:
            self.stop()

    def _has_response(self, sock):
        if select.select((sock, ), (), (), 0)[0]:
            return True
        else:
            return False
