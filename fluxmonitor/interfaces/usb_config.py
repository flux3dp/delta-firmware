
from pkg_resources import resource_string
from binascii import a2b_base64
import logging

from fluxmonitor.hal.net.monitor import Monitor as NetworkMonitor
from fluxmonitor.hal.nl80211.config import get_wlan_ssid
from fluxmonitor.hal.nl80211.scan import scan as scan_wifi
from fluxmonitor.security import (AccessControl, validate_password,
                                  set_password, get_keyobj, RSAObject)
from fluxmonitor.storage import metadata
from fluxmonitor.err_codes import (AUTH_ERROR, NOT_FOUND,
                                   UNKNOWN_COMMAND, UNKNOWN_ERROR)
from fluxmonitor.config import CONFIGURE_ENDPOINT
from .listener import UnixStreamInterface
from .handler import MsgpackProtocol, UnixHandler

access_control = AccessControl.instance()
logger = logging.getLogger(__name__)


class ConfigureTools(object):
    @classmethod
    def request_set_nickname(cls, nickname):
        metadata.nickname = nickname

    @classmethod
    def request_set_password(cls, oldpasswd, password, clear_acl):
        if validate_password(oldpasswd):
            set_password(password)
            if clear_acl:
                access_control.remove_all()
        else:
            raise RuntimeError(AUTH_ERROR)

    @classmethod
    def request_reset_password(cls, password, pem=None, label=None):
        set_password(password)
        access_control.remove_all()
        if pem:
            cls.request_add_trust(label or "noname", pem)

    @classmethod
    def request_list_trust(cls):
        return access_control.list()

    @classmethod
    def request_add_trust(cls, label, pem):
        keyobj = RSAObject(pem=pem)
        if keyobj:
            if access_control.is_trusted(keyobj=keyobj):
                raise RuntimeError("OPERATION_ERROR")
            access_control.add(keyobj, label=label)
        else:
            raise RuntimeError("BAD_PARAMS")

    @classmethod
    def request_remove_trust(cls, access_id):
        if not access_control.remove(access_id):
            raise RuntimeError(NOT_FOUND)

    @classmethod
    def request_get_wifi(cls, ifname):
        return {"ssid": get_wlan_ssid(ifname)}

    @classmethod
    def request_get_ipaddr(cls, ifname):
        nm = NetworkMonitor(None)
        try:
            ipaddrs = nm.get_ipaddresses(ifname)
            return {"ipaddrs": ipaddrs}
        finally:
            nm.close()
        return get_wlan_ssid(ifname)

    @classmethod
    def request_scan_wifi(cls):
        return scan_wifi()

    # diagnosis api
    @classmethod
    def request__enable_tty(cls, salt, signature):
        pem = resource_string("fluxmonitor", "data/develope.pem")
        rsakey = get_keyobj(pem=pem)

        if rsakey.verify(salt, a2b_base64(signature)):
            from fluxmonitor.diagnosis.usb2device import enable_console
            ret = enable_console()
            if ret != 0:
                raise RuntimeError("EXEC_ERROR_%s" % ret)
        else:
            raise RuntimeError("SIGNATURE_ERROR")

    # diagnosis api
    @classmethod
    def request__enable_ssh(cls, salt, signature):
        pem = resource_string("fluxmonitor", "data/develope.pem")
        rsakey = get_keyobj(pem=pem)

        if rsakey.verify(salt, a2b_base64(signature)):
            from fluxmonitor.diagnosis.usb2device import enable_ssh
            ret = enable_ssh()
            if ret != 0:
                raise RuntimeError("EXEC_ERROR_%s" % ret)
        else:
            raise RuntimeError("SIGNATURE_ERROR")


class UsbConfigInternalInterface(UnixStreamInterface):
    def __init__(self, kernel, endpoint=CONFIGURE_ENDPOINT):
        super(UsbConfigInternalInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        return UsbConfigInternalHandler(self.kernel, endpoint, sock)


class UsbConfigInternalHandler(MsgpackProtocol, UnixHandler):
    def on_connected(self):
        super(UsbConfigInternalHandler, self).on_connected()
        self.on_ready()

    def on_payload(self, obj):
        req_method = "request_" + (obj[0]).decode("ascii", "ignore")
        logger.debug("Request: %s", req_method)

        if hasattr(ConfigureTools, req_method):
            try:
                ret = getattr(ConfigureTools, req_method)(*obj[1], **obj[2])
                if ret is None:
                    self.send_payload({"status": "ok"})
                elif isinstance(ret, dict):
                    self.send_payload({"status": "ok", "result": ret})
                else:
                    for element in ret:
                        self.send_payload({"status": "data", "data": element})
                    self.send_payload({"status": "ok"})
            except RuntimeError as err:
                self.send_payload({"status": "error", "error": err.args})
            except Exception:
                logger.exception("Configure device error")
                self.send_payload({"status": "error",
                                  "error": (UNKNOWN_ERROR, )})
        else:
            self.send_payload({"status": "error",
                               "error": (UNKNOWN_COMMAND, )})
