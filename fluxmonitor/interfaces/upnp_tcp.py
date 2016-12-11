
from binascii import a2b_hex as from_hex
import logging
import json
import os

from fluxmonitor.err_codes import (UNKNOWN_ERROR, BAD_PARAMS, AUTH_ERROR,
                                   UNKNOWN_COMMAND)
from fluxmonitor.security import (RSAObject, AccessControl, hash_password,
                                  get_uuid, validate_password)
from .listener import SSLInterface
from .handler import SSLHandler, TextBinaryProtocol
from .usb_config_client import UsbConfigInternalClient

__all__ = ["UpnpTcpInterface", "UpnpTcpHandler"]
logger = logging.getLogger(__name__)
access_control = AccessControl.instance()
UUID_BIN = from_hex(get_uuid())


class UpnpTcpInterface(SSLInterface):
    _empty = True

    def __init__(self, kernel, endpoint=("", 1901)):
        super(UpnpTcpInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        logger.debug("Incomming connection from %s", endpoint)
        h = UpnpTcpHandler(self.kernel, endpoint, sock, server_side=True,
                           certfile=self.certfile, keyfile=self.keyfile)
        return h


class UpnpTcpHandler(TextBinaryProtocol, SSLHandler):
    client_key = None
    authorized = False
    randbytes = None
    client = None
    client_ready = False

    def on_connected(self):
        self.sock.send(b"FLUX0003")
        super(UpnpTcpHandler, self).on_connected()

    def on_ssl_connected(self):
        super(UpnpTcpHandler, self).on_ssl_connected()
        self.randbytes = os.urandom(64)
        self.sock.send(self.randbytes)
        self.on_ready()

    def on_upnp_authorized(self):
        self.client = UsbConfigInternalClient(
            self.kernel,
            on_connected_callback=self.on_subsystem_ready,
            on_close_callback=self.on_subsystem_closed)
        self.client.payload_callback = self.on_subsystem_response
        self.authorized = True

    def on_subsystem_ready(self, *args):
        self.client_ready = True
        self.send_text("ok")

    def on_subsystem_closed(self, handler, error):
        if self.client_ready:
            logger.debug("Subsystem closed")
            self.client_ready = False
            self.on_error()

    def on_subsystem_response(self, handler, obj):
        st = obj["status"]
        if st == "ok":
            self.send_text("ok")
        elif st == "error":
            self.send_text("error " + " ".join(obj["error"]))
        elif st == "data":
            self.send_text("data " + json.dumps(obj["data"]))

    def close(self):
        super(UpnpTcpHandler, self).close()
        if self.client_ready:
            self.client_ready = False
            self.client.close()

    def process_request(self, cmd, *args):
        if cmd == "passwd":
            if len(args) == 2:
                old_password, new_password = args
                self.client.set_password(old_password, new_password)
            else:
                old_password, new_password, clean_acl = args
                self.client.set_password(old_password, new_password,
                                         clean_acl == "Y")
        elif cmd == "add_trust":
            label, pem = args
            self.client.add_trust(label, pem)
        elif cmd == "list_trust":
            self.client.list_trust()
        elif cmd == "remove_trust":
            self.client.remove_trust(args[0])
        elif cmd == "network":
            raw_config = {}
            for pair in args:
                if "=" not in pair:
                    continue
                k, v = pair.split("=")
                raw_config[k] = v

            if "ifname" not in raw_config:
                raw_config["ifname"] = "wlan0"

            try:
                request_data = self.client.validate_network_config(raw_config)
            except KeyError as e:
                raise RuntimeError("BAD_PARAMS", e.args[0])

            try:
                def callback():
                    self.send_text("ok")

                self.client.send_network_config(request_data, callback)
            except IOError:
                raise RuntimeError("SUBSYSTEM_ERROR")

        elif cmd == "rename":
            self.client.set_nickname(args[0])
        elif cmd == "scan_wifi":
            self.client.scan_wifi()
        elif cmd == "get_vector":
            self.send_text("ok " + self.client.vector)
        elif cmd == "enable_tty":
            self.client.enable_tty(args[0])
        elif cmd == "enable_ssh":
            self.client.enable_ssh(args[0])
        else:
            self.send_text("error " + UNKNOWN_COMMAND)

    def on_text(self, message):
        if self.client_ready:
            args = message.split("\x00")
            cmd = args.pop(0)
            try:
                self.process_request(cmd, *args)

            except RuntimeError as e:
                self.send_text("er " + " ".join(e.args))
            except IOError as e:
                logger.debug("Connection close: %s" % e)
                self.on_error()
            except Exception:
                logger.exception("Unknown error during process command")
                self.send_text("UNKNOWN_ERROR")
                self.on_error()
        elif self.authorized:
            logger.error("Recv request before subsystem ready, close conn")
            self.send_text("PROTOCOL_ERROR")
            self.on_error()
        elif self.client_key:
            try:
                if access_control.is_trusted(keyobj=self.client_key):
                    document = hash_password(UUID_BIN, self.randbytes)
                    if self.client_key.verify(document, from_hex(message)):
                        logger.debug("Remote sign ok, connect to subsystem")
                        self.on_upnp_authorized()
                    else:
                        logger.debug("Remote sign error")
                        self.send_text("error " + AUTH_ERROR)
                        self.close()
                else:
                    if validate_password(message.decode("utf8")):
                        logger.debug("Remote password ok")
                        self.on_upnp_authorized()
                    else:
                        logger.debug("Remote password error")
                        self.send_text("error " + AUTH_ERROR)
                        self.close()
            except IOError as e:
                logger.debug("Connection close: %s" % e)
                self.on_error()
            except Exception:
                self.send_text("error " + UNKNOWN_ERROR)
                self.on_error()
                logger.exception("Error while parse rsa key")

        else:
            try:
                self.client_key = k = RSAObject(pem=message)
                if access_control.is_trusted(keyobj=k):
                    logger.debug("Remote need sign")
                    self.send_text("sign")
                else:
                    logger.debug("Remote need password")
                    self.send_text("password")
            except TypeError:
                self.send_text("error " + BAD_PARAMS)
                self.close()
            except IOError as e:
                logger.debug("Connection close: %s" % e)
                self.on_error()
            except Exception:
                self.send_text("error " + UNKNOWN_ERROR)
                self.on_error()
                logger.exception("Error while parse rsa key")
