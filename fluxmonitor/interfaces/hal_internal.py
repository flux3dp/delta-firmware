
import logging

from fluxmonitor.config import HALCONTROL_ENDPOINT
from .listener import UnixStreamInterface
from .handler import MsgpackProtocol, UnixHandler

logger = logging.getLogger(__name__)


class HalControlInterface(UnixStreamInterface):
    def __init__(self, kernel, endpoint=HALCONTROL_ENDPOINT):
        super(HalControlInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        return HalControlHandler(self.kernel, endpoint, sock)


class HalControlHandler(MsgpackProtocol, UnixHandler):
    def on_connected(self):
        self.on_ready()

    def send_event(self, event):
        self.send_payload((1, event))

    def on_payload(self, payload):
        cmd = payload[0]
        resp = payload[1]

        try:
            if cmd == "reconnect":
                self.kernel.reconnect()
            elif cmd == "reset_mb":
                self.kernel.reset_mainboard()
            elif cmd == "th_pow_on":
                self.kernel.toolhead_power_on()
            elif cmd == "th_pow_off":
                self.kernel.toolhead_power_off()
            elif cmd == "th_on":
                self.kernel.toolhead_on()
            elif cmd == "th_standby":
                self.kernel.toolhead_standby()
            elif cmd == "update_head_fw":
                def cb(message):
                    if resp:
                        self.send_payload((0, "proc", message))
                self.kernel.update_head_fw(cb)
            elif cmd == "update_fw":
                self.kernel.update_main_fw()
            elif cmd == "diagnosis_mode":
                self.send_payload((0, self.kernel.diagnosis_mode(), ))
            elif cmd == "bye":
                resp = False

            if resp:
                self.send_payload((0, "ok",))
            else:
                self.close()
        except RuntimeError as e:
            logger.debug("RuntimeError%s", e)
            if resp:
                self.send_payload((0, "error", ) + e.args)
        except Exception:
            logger.exception("Hal request error")
            if resp:
                self.send_payload((0, "error", "UNKNOWN_ERROR"))
            self.on_error()


class HalControlClientHandler(MsgpackProtocol, UnixHandler):
    _on_btn_ev_cb = None
    _temp_callback = None

    def __init__(self, kernel, endpoint=HALCONTROL_ENDPOINT,
                 on_close_callback=None, on_button_event_callback=None):
        super(HalControlClientHandler, self).__init__(
            kernel, endpoint, on_close_callback=on_close_callback)
        self._on_btn_ev_cb = on_button_event_callback

    def on_connected(self):
        super(HalControlClientHandler, self).on_connected()
        self.on_ready()

    def on_payload(self, payload):
        tp = payload[0]
        if tp == 0 and self._temp_callback:
            try:
                self._temp_callback(payload[1:], self)
            except Exception:
                logger.exception("Error in hal response callback")
        elif tp == 1 and self._on_btn_ev_cb:
            self._on_btn_ev_cb(payload[1], self)

    def request_update_atmel(self):
        self.send_payload(("update_fw", False))

    def request_update_toolhead(self, callback):
        self.send_payload(("update_head_fw", True))
        self._temp_callback = callback
