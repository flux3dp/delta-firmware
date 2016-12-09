
from select import select
from errno import errorcode
import socket

from fluxmonitor.config import CONFIGURE_ENDPOINT, NETWORK_MANAGE_ENDPOINT
from fluxmonitor.misc import network_config_encoder as NCE  # noqa
from .handler import MsgpackProtocol, UnixHandler


class UsbConfigInternalClient(MsgpackProtocol, UnixHandler):
    payload_callback = None

    def __init__(self, kernel, endpoint=CONFIGURE_ENDPOINT, sock=None,
                 **kw):
        UnixHandler.__init__(self, kernel, endpoint, sock, False, **kw)

    def on_connected(self):
        super(UsbConfigInternalClient, self).on_connected()
        self.on_ready()

    def on_payload(self, data):
        if self.payload_callback:
            self.payload_callback(self, data)

    def send_request(self, command, *args, **kw):
        self.send_payload((command, args, kw))

    def set_password(self, oldpasswd, password, clear_acl=True):
        self.send_request("set_password", oldpasswd, password, clear_acl)

    def set_nickname(self, nickname):
        self.send_request("set_nickname", nickname)

    def list_trust(self):
        self.send_request("list_trust")

    def add_trust(self, label, pem):
        self.send_request("add_trust", label, pem)

    def remove_trust(self, access_id):
        self.send_request("remove_trust", access_id)

    def get_wifi(self, ifname="wlan0"):
        self.send_request("get_wifi", ifname)

    def get_ipaddr(self, ifname="wlan0"):
        self.send_request("get_ipaddr", ifname)

    def scan_wifi(self):
        self.send_request("scan_wifi")

    def validate_network_config(self, config):
        validated_config = NCE.validate_options(config)
        request_data = ("config_network" + "\x00" +
                        NCE.to_bytes(validated_config)).encode()
        return request_data

    def send_network_config(self, request_data, before_send_callback=None):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)
        ret = sock.connect_ex(NETWORK_MANAGE_ENDPOINT)
        if ret != 0:
            raise IOError("Async connect to endpoint error: %s" %
                          errorcode.get(ret))
        select((), (sock, ), (), 0.05)
        if before_send_callback:
            before_send_callback()

        sock.send(request_data)
        sock.close()
