
from time import time, sleep
import logging
import re

from fluxmonitor.err_codes import EXEC_HEADER_OFFLINE, EXEC_OPERATION_ERROR, \
    EXEC_WRONG_HEADER

NAN = float("nan")

IDENTIFY_PARSER = re.compile("FLUX (?P<module>\w+) Module")
TEMP_PARSER = re.compile("ok@RT: (?P<temp>\d+)")

TYPE_3DPRINT = 0
TYPE_LASER = 1
TYPE_PENHOLDER = 2

L = logging.getLogger(__name__)


def get_head_controller(head_type, *args, **kw):
    if head_type == TYPE_3DPRINT:
        return ExtruderController(*args, **kw)


def module_name_conv(orig_text):
    if orig_text == "Printer":
        return "extruder"
    else:
        return orig_text


class HeaderController(object):
    def __init__(self):
        pass

    def on_loop(self):
        pass


class ExtruderController(HeaderController):
    # FSM
    # (use this data to recover status if headbored reconnected)
    _fanspeed = 0
    _temperatures = None

    # On-the-fly status
    _ready = False
    _ready_callback = None
    _current_temp = None

    _cmd_sent_at = 0
    _cmd_retry = 0
    _padding_cmd = None
    _cmd_callback = None

    _lastupdate = 0
    _update_retry = 0
    _wait_update = False

    _recover_queue = None

    def __init__(self, executor, ready_callback):
        self._temperatures = [float("NaN")]
        self._ready_callback = ready_callback

        # On-the-fly status
        self._current_temp = [float("NaN")]
        self.bootstrap(executor)

    def bootstrap(self, executor):
        self._cmd_sent_at = 0
        self._cmd_retry = 0
        self._padding_cmd = None
        self._cmd_callback = None
        self._heaters_callback = None

        self._lastupdate = 0
        self._update_retry = 0
        self._wait_update = False

        queue = ["RM\n"]
        if self._temperatures[0] > 0:
            queue.append("H%i\n" % (self._temperatures[0] * 10))
        queue.append("F1%i\n" % (self._fanspeed * 255))

        self._recover_queue = queue
        self._padding_cmd = queue.pop(0)
        self._send_cmd(executor)

    @property
    def ready(self):
        return self._ready

    @property
    def is_busy(self):
        return self._padding_cmd != None

    def status(self):
        return {
            "module": "executor",
            "t": (self._temperatures[0], )
        }

    def set_heater(self, executor, heater_id, temperature, callback=None):
        if self._padding_cmd:
            self._raise_error(EXEC_OPERATION_ERROR,
                              "Busy: %s" % self._padding_cmd)

        if temperature < 5:
            raise RuntimeError(EXEC_OPERATION_ERROR, "BAD TEMP")
        elif temperature > 245:
            raise SystemError(EXEC_OPERATION_ERROR, "BAD TEMP")

        self._temperatures[0] = temperature
        if temperature is NAN:
            self._padding_cmd = "HF%i\n" % (temperature * 10)
        else:
            self._padding_cmd = "HO%i\n" % (temperature * 10)

        self._send_cmd(executor)
        self._cmd_callback = callback

    def set_fanspeed(self, executor, fan_id, fan_speed, callback=None):
        if self._padding_cmd:
            self._raise_error(EXEC_OPERATION_ERROR,
                              "Busy: %s" % self._padding_cmd)

        self._fanspeed = f = max(min(1.0, fan_speed), 0)
        self._padding_cmd = "F1%i\n" % (f * 255)
        self._send_cmd(executor)
        self._cmd_callback = callback

    def wait_heaters(self, callback):
        self._heaters_callback = callback

    def on_message(self, msg, executor):
        if not msg:
            return

        if self._ready and self._parse_cmd_response(msg, executor):
            return

        elif "ok@RT" in msg:
            m = TEMP_PARSER.search(msg)
            if m:
                temp = float(m.groupdict()['temp']) / 10.0
                self._current_temp[0] = temp
                self._update_retry = 0
                self._wait_update = False
                self._lastupdate = time()

                if self._heaters_callback:
                    if self._temperatures[0] is None:
                        self._heaters_callback(self)
                        self._heaters_callback = None

                    if not (self._temperatures[0] > 0):
                        self._heaters_callback(self)
                        self._heaters_callback = None
                    elif abs(self._temperatures[0] -
                           self._current_temp[0]) < 3:
                        self._heaters_callback(self)
                        self._heaters_callback = None
                return
        else:
            if self._padding_cmd == "RM\n":
                m = IDENTIFY_PARSER.search(msg)
                if m:
                    self.module = module_name_conv(m.groupdict().get('module'))
                    if self.module == "extruder":
                        self._cmd_sent_at = 0
                        self._cmd_retry = 0
                        self._padding_cmd = None
                        self._cmd_callback = None

                        if self._recover_queue:
                            self._padding_cmd = self._recover_queue.pop(0)
                            self._send_cmd(executor)
                        else:
                            self._on_ready(executor)
                    else:
                        self._raise_error(EXEC_WRONG_HEADER)
                return
            else:
                if self._parse_cmd_response(msg, executor):
                    if self._recover_queue:
                        self._padding_cmd = self._recover_queue.pop(0)
                        self._cmd(executor)
                    else:
                        self._on_ready(executor)
                    return

        if msg == "[Event]:1":
            L.error("Recive header boot")
            self._raise_error(EXEC_HEADER_OFFLINE)

        L.debug("Recv unknow msg: '%s'", msg)

    def send_cmd(self, cmd, executor, waitting_callback=None):
        if cmd.startswith("H"):
            target_temp = float(cmd[1:])
            self.set_heater(executor, 0, target_temp)
            self.wait_heaters(waitting_callback)
        elif cmd.startswith("F"):
            target_speed = float(cmd[1:])
            self.set_fanspeed(executor, 0, target_speed)
            self.wait_heaters(waitting_callback)
        else:
            raise SystemError("UNKNOW_COMMAND", "HEAD_MESSAGE")

    def _on_ready(self, executor):
        self._ready = True
        if self._ready_callback:
            self._ready_callback(self)

    def _make_delay(self):
        delay = 0.75 - (time() - max(self._lastupdate, self._cmd_sent_at))
        if delay > 0:
            # Make a delay to prevent head crash
            sleep(delay)

    def _send_cmd(self, executor):
        self._make_delay()
        executor.send_headboard(self._padding_cmd)
        self._cmd_sent_at = time()

    def _send_update(self, executor):
        self._make_delay()
        executor.send_headboard("RT\n")
        self._wait_update = True
        self._lastupdate = time()

    def _parse_cmd_response(self, msg, executor):
        if self._padding_cmd and self._padding_cmd.strip() in msg:
            try:
                if self._cmd_callback:
                    self._cmd_callback(executor)
            finally:
                self._cmd_sent_at = 0
                self._cmd_retry = 0
                self._padding_cmd = None
                self._cmd_callback = None
            return True
        return False

    def patrol(self, executor):
        if self._ready:
            if self._wait_update:
                if self._update_retry > 2:
                    self._raise_error(EXEC_HEADER_OFFLINE)
                elif time() - self._lastupdate > 1.5:
                    self._send_update(executor)
                    self._update_retry += 1
                    L.debug("Header no response T, retry (%i)",
                            self._update_retry)

            elif time() - self._lastupdate > 1.0:
                self._send_update(executor)
                self._wait_update = True

        if self._padding_cmd:
            if self._cmd_retry > 2:
                self._raise_error(EXEC_HEADER_OFFLINE)
            elif time() - self._cmd_sent_at > 1.5:
                self._send_cmd(executor)
                self._cmd_retry += 1
                L.debug("Header no response, retry (%i)", self._update_retry)

    def _raise_error(self, *args):
        self._ready = False
        raise RuntimeError(*args)
