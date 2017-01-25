
from fluxmonitor.security.misc import randstr
from fluxmonitor.config import CONFIGURE_ENDPOINT
from fluxmonitor.misc import network_config_encoder as NCE  # noqa
from .handler import MsgpackProtocol, UnixHandler


class UsbConfigInternalClient(MsgpackProtocol, UnixHandler):
    payload_callback = None

    def __init__(self, kernel, endpoint=CONFIGURE_ENDPOINT, sock=None,
                 **kw):
        UnixHandler.__init__(self, kernel, endpoint, sock, False, **kw)
        self.vector = randstr(8)

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

    def reset_password(self, password):
        self.send_request("reset_password", password)

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

    def get_vector(self):
        self.on_payload({"status": "ok", "result": self.vector})

    def enable_tty(self, signature):
        self.send_request("_enable_tty", self.vector, signature)

    def enable_ssh(self, signature):
        self.send_request("_enable_ssh", self.vector, signature)

    def validate_network_config(self, config):
        return NCE.build_network_config_request(config)

    def send_network_config(self, request_data, before_send_callback=None):
        return NCE.send_network_config_request(request_data,
                                               before_send_callback)
