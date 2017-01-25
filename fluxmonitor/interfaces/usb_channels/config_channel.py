
import logging

from fluxmonitor.interfaces.usb_config_client import UsbConfigInternalClient
from fluxmonitor.security import validate_password

CMD_LIST = ("set_password", "set_nickname", "list_trust", "add_trust",
            "remove_trust", "get_ipaddr", "get_wifi", "scan_wifi",
            "reset_password")
logger = logging.getLogger(__name__)


class ConfigChannel(object):
    client = None

    @classmethod
    def validate_password(cls, passwd):
        return validate_password(passwd)

    def __init__(self, index, protocol):
        self.index = index
        self.protocol = protocol
        self.client = UsbConfigInternalClient(
            protocol.kernel,
            on_connected_callback=self.on_subsystem_ready,
            on_close_callback=self.on_subsystem_closed)
        self.client.payload_callback = self.on_response
        logger.debug("Config channel opened")

    def __str__(self):
        return "<ConfigChannel@%i>" % (self.index)

    def on_subsystem_ready(self, *args):
        pass

    def on_subsystem_closed(self, handler, error):
        self.client = None

    def on_set_network(self, config):
        try:
            if "ifname" not in config:
                config["ifname"] = "wlan0"

            request_data = self.client.validate_network_config(config)
            self.client.send_network_config(request_data)
            self.protocol.send_payload(self.index, {"status": "ok"})
        except KeyError as e:
            logger.info("Network config broken: %s (error=%s)", config, e)
            self.protocol.send_payload(
                self.index,
                {"status": "error", "error": ("BAD_PARAMS", e.args[0])})

    def on_response(self, client, obj):
        self.protocol.send_payload(self.index, obj)

    def on_payload(self, obj):
        cmd = obj.get("cmd")
        if cmd in CMD_LIST:
            logger.debug("Request: %s", cmd)
            fn = getattr(self.client, cmd)
            fn(**obj.get("options", {}))
        elif cmd == "set_network":
            self.on_set_network(obj.get("options", {}))
        else:
            self.protocol.send_payload(self.index,
                                       {"status": "error",
                                        "error": ("UNKNOWN_COMMAND", )})

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
