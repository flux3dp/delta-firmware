
from binascii import a2b_hex as from_hex
from weakref import proxy
import logging
import json
import ssl

import pyev

from fluxmonitor.hal.nl80211.scan import scan as scan_wifi
from fluxmonitor.err_codes import (UNKNOWN_ERROR, BAD_PARAMS, AUTH_ERROR,
                                   UNKNOWN_COMMAND)
from fluxmonitor.security import (RSAObject, is_trusted_remote, hash_password,
                                  get_uuid)
from .tcp_ssl import SSLInterface, SSLConnectionHandler

__all__ = ["UpnpTcpInterface", "UpnpTcpHandler"]
logger = logging.getLogger(__name__)
UUID_BIN = from_hex(get_uuid())


class UpnpTcpInterface(SSLInterface):
    _empty = True

    def __init__(self, kernel, endpoint=("", 1901)):
        super(UpnpTcpInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        h = UpnpTcpHandler(self.kernel, sock, endpoint, self.certfile,
                           self.keyfile)
        return h


class UpnpTcpHandler(SSLConnectionHandler):
    client_key = None
    authorized = False

    def _on_ssl_handshake(self, watcher=None, revent=None):
        if self.send_watcher:
            self.send_watcher.stop()
            self.send_watcher = None

        try:
            self.sock.do_handshake()
            self.logger.debug("SSL READY")
            self.sock.send(self.randbytes)

            # SSL Handshake ready, prepare buffer
            self._buf = bytearray(4096)
            self._bufview = memoryview(self._buf)
            self._buffered = 0
            self._on_ready()

        except ssl.SSLWantReadError:
            pass
        except ssl.SSLWantWriteError:
            self.send_watcher = self.kernel.loop.io(
                self.sock, pyev.EV_WRITE, self._do_ssl_handshake)
        except Exception:
            logger.exception("SSL handshake failed")
            self.close()

    def on_ready(self):
        self.delegate = proxy(self)

    def on_close(self, _):
        pass

    def on_text(self, message, _):
        if self.authorized:
            args = message.split("\x00")
            cmd = args.pop(0)

            try:
                if cmd == "passwd":
                    self.on_passwd(*args)
                elif cmd == "network":
                    self.on_network(*args)
                elif cmd == "rename":
                    self.on_rename(*args)
                elif cmd == "scan_wifi":
                    self.on_scan_wifi(*args)
                else:
                    self.send_text("error " + UNKNOWN_COMMAND)
            except RuntimeError as e:
                self.send_text("error " + " ".join(e.args))
            except Exception:
                logger.exception("Unknown error during process command")
                self.send_text("UNKNOWN_ERROR")
                self.close()

        elif self.client_key:
            try:
                if is_trusted_remote(keyobj=self.client_key):
                    document = hash_password(UUID_BIN, self.randbytes)
                    if self.client_key.verify(document, from_hex(message)):
                        logger.debug("Remote sign ok")
                        self.send_text("ok")
                        self.authorized = True
                    else:
                        logger.debug("Remote sign error")
                        self.send_text("error " + AUTH_ERROR)
                        self.close()
                else:
                    if self.kernel.on_auth(self.client_key, message):
                        logger.debug("Remote password ok")
                        self.send_text("ok")
                        self.authorized = True
                    else:
                        logger.debug("Remote password error")
                        self.send_text("error " + AUTH_ERROR)
                        self.close()
            except Exception:
                self.send_text("error " + UNKNOWN_ERROR)
                self.close()
                logger.exception("Error while parse rsa key")

        else:
            try:
                self.client_key = k = RSAObject(pem=message)
                if is_trusted_remote(keyobj=k):
                    logger.debug("Remote need sign")
                    self.send_text("sign")
                else:
                    logger.debug("Remote need password")
                    self.send_text("password")
            except TypeError:
                self.send_text("error " + BAD_PARAMS)
                self.close()
            except Exception:
                self.send_text("error " + UNKNOWN_ERROR)
                self.close()
                logger.exception("Error while parse rsa key")

    def on_passwd(self, old_password, new_password, clean_acl="Y"):
        try:
            if self.kernel.on_modify_passwd(self.client_key, old_password,
                                            new_password, clean_acl == "Y"):
                self.send_text("ok")
            else:
                self.send_text("error " + AUTH_ERROR)
        except Exception:
            logger.exception("Upnp tcp on_passwd error")
            self.send_text("error " + UNKNOWN_ERROR)

    def on_network(self, *raw_config):
        config = {}
        for pair in raw_config:
            if "=" not in pair:
                continue
            k, v = pair.split("=")
            config[k] = v

        try:
            if "ifname" in config:
                if config["ifname"] not in ["wlan0", "wlan1", "len0", "len1"]:
                    raise RuntimeError(BAD_PARAMS, "ifname")
            else:
                config["ifname"] = "wlan0"

            self.kernel.on_modify_network(config)
        except RuntimeError as e:
            self.send_text("error " + " ".join(e.args))

        except KeyError as e:
            self.send_text("error " + BAD_PARAMS + " " + e.args[0])

        except Exception:
            logger.exception("Upnp tcp on_network error")
            self.send_text("error " + UNKNOWN_ERROR)

    def on_rename(self, new_name):
        if new_name:
            self.kernel.on_rename_device(new_name)
        else:
            self.send_text("error " + BAD_PARAMS)

    def on_scan_wifi(self):
        for r in scan_wifi():
            self.send_text("data " + json.dumps(r))

        self.send_text("ok")
