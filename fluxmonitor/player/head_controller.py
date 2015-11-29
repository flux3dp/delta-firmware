
from shlex import split as shlex_split
from time import time
import logging

from fluxmonitor.err_codes import EXEC_HEADER_OFFLINE, EXEC_OPERATION_ERROR, \
    EXEC_WRONG_HEADER

TYPE_3DPRINT = 0
TYPE_LASER = 1
TYPE_PENHOLDER = 2

L = logging.getLogger(__name__)


def create_chksum_cmd(fmt, *args):
    s = 0
    cmd = fmt % args
    for c in cmd:
        s ^= ord(c)
    s ^= 32
    return "%s *%i\n" % (cmd, s)


def get_head_controller(head_type, *args, **kw):
    if head_type == TYPE_3DPRINT:
        return ExtruderController(*args, **kw)


class ExtruderController(object):
    _module = None

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
        self._ready = False
        self._cmd_sent_at = 0
        self._cmd_retry = 0
        self._padding_cmd = None
        self._cmd_callback = None
        self._heaters_callback = None

        self._lastupdate = 0
        self._update_retry = 0
        self._wait_update = False

        queue = ["1 HELLO *115\n"]
        if self._temperatures[0] > 0:
            queue.append(
                create_chksum_cmd("1 H:%i T:%.1f", 0, self._temperatures[0]))
        queue.append(
            create_chksum_cmd("1 F:%i S:%i", 0, self._fanspeed * 255))

        self._recover_queue = queue
        self._padding_cmd = queue.pop(0)
        self._send_cmd(executor)

    @property
    def ready(self):
        return self._ready

    @property
    def is_busy(self):
        return self._padding_cmd is not None

    @property
    def module(self):
        return self._module

    def status(self):
        return {
            "module": self.module,
            "tt": (self._temperatures[0], ),
            "rt": (self._current_temp[0], ),
            "tf": (self._fanspeed, )
        }

    def set_heater(self, executor, heater_id, temperature, callback=None):
        if self._padding_cmd:
            self._raise_error(EXEC_OPERATION_ERROR,
                              "Busy: %s" % self._padding_cmd)

        if temperature < 5:
            raise RuntimeError(EXEC_OPERATION_ERROR, "BAD TEMP")
        elif temperature > 280:
            raise SystemError(EXEC_OPERATION_ERROR, "BAD TEMP")

        self._temperatures[0] = temperature
        self._padding_cmd = create_chksum_cmd("1 H:%i T:%.1f", heater_id,
                                              temperature)
        self._cmd_callback = callback
        self._send_cmd(executor)

    def set_fanspeed(self, executor, fan_id, fan_speed, callback=None):
        if self._padding_cmd:
            self._raise_error(EXEC_OPERATION_ERROR,
                              "Busy: %s" % self._padding_cmd)

        self._fanspeed = f = max(min(1.0, fan_speed), 0)
        self._padding_cmd = create_chksum_cmd("1 F:%i S:%i", fan_id, f * 255)
        self._send_cmd(executor)
        self._cmd_callback = callback

    def wait_heaters(self, callback):
        self._heaters_callback = callback

    def on_message(self, raw_message, executor):
        if raw_message.startswith("1 "):
            s = l = 0
            for c in raw_message:
                if c == "*":
                    break
                else:
                    s ^= ord(c)
                    l += 1

            try:
                val = int(raw_message[l + 1:], 10)
                if val != s:
                    return
            except ValueError:
                return

            self.handle_message(raw_message[2:l], executor)

    def handle_message(self, msg, executor):
        if self._ready:
            if msg.startswith("OK PONG "):
                self._handle_pong(msg, executor)
                return

            elif self._parse_cmd_response(msg, executor):
                return

        else:
            if self._padding_cmd == "1 HELLO *115\n":
                if msg.startswith("OK HELLO "):
                    module_info = {}
                    for param in shlex_split(msg[9:]):
                        sparam = param.split(":", 1)
                        if len(sparam) == 2:
                            module_info[sparam[0]] = sparam[1]

                    self._module = module_info.get("TYPE", "UNKNOW")
                    if self.module == "EXTRUDER":
                        self._cmd_sent_at = 0
                        self._cmd_retry = 0
                        self._padding_cmd = None
                        self._cmd_callback = None

                        if self._recover_queue:
                            self._padding_cmd = self._recover_queue.pop(0)
                            self._send_cmd(executor)
                        else:
                            self._ready = True
                            if self._ready_callback:
                                self._ready_callback(self)
                    else:
                        self._raise_error(EXEC_WRONG_HEADER)
            else:
                if self._parse_cmd_response(msg, executor):
                    if self._recover_queue:
                        self._padding_cmd = self._recover_queue.pop(0)
                        self._send_cmd(executor)
                    else:
                        self._ready = True
                        if self._ready_callback:
                            self._ready_callback(self)

        L.info("RECV_UH: '%s'", msg)

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

    def _send_cmd(self, executor):
        if not self._wait_update:
            executor.send_headboard(self._padding_cmd)
            self._cmd_sent_at = time()

    def _parse_cmd_response(self, msg, executor):
        if msg.startswith("OK "):
            # Clear padding cmd
            try:
                if self._cmd_callback:
                    self._cmd_callback(executor)
            finally:
                self._cmd_sent_at = 0
                self._cmd_retry = 0
                self._padding_cmd = None
                self._cmd_callback = None
            return True
        elif msg.startswith("ER "):
            err = shlex_split(msg[3:])
            raise RuntimeError(EXEC_HEADER_OFFLINE, *err)

        else:
            return False

    def _handle_ping(self, executor):
        executor.send_headboard("1 PING *33\n")
        self._wait_update = True
        self._lastupdate = time()

    def _handle_pong(self, msg, executor):
        self._update_retry = 0
        self._wait_update = False
        self._lastupdate = time()

        for param in shlex_split(msg[8:]):
            status = param.split(":", 1)
            if len(status) != 2:
                # params should be "KEY:VALUE"
                L.error("Unknow pong param: %s", param)

            elif status[0] == "RT":
                self._current_temp[0] = float(status[1])
                if self._heaters_callback:
                    if not (self._temperatures[0] > 0):
                        self._heaters_callback(self)
                        self._heaters_callback = None
                    elif abs(self._temperatures[0] -
                             self._current_temp[0]) < 3:
                        self._heaters_callback(self)
                        self._heaters_callback = None

            elif status[0] == "ER":
                try:
                    er = int(status[1])
                except ValueError:
                        L.error("Head er flag failed")
                        self._raise_error(EXEC_HEADER_OFFLINE,
                                          "ER_ERROR")

                if er > 0:
                    if er & 4:
                        self._raise_error(EXEC_HEADER_OFFLINE,
                                          "HEAD_RESET")
                    if er & 8:
                        self._raise_error("HEAD_CALIBRATION_FAILED")
                    if er & 16:
                        self._raise_error("HEAD_SHAKE")
                    if er & 32:
                        self._raise_error("HEAD_TILT")
                    if er & 64:
                        self._raise_error("HEAD_FAILED", "PID_OUT_OF_CONTROL")
                    if er & 128:
                        self._raise_error("HEAD_FAILED", "FAN_FAILURE")

        if self._padding_cmd:
            self._send_cmd(executor)

    def patrol(self, executor, strict=True):
        if self._wait_update:
            if self._update_retry > 2 and strict:
                self._raise_error(EXEC_HEADER_OFFLINE)
            if time() - self._lastupdate > 1.5:
                self._handle_ping(executor)
                self._update_retry += 1 if strict else 0
                L.debug("Header ping timeout, retry (%i)", self._update_retry)

        if self._padding_cmd:
            if self._cmd_retry > 2 and strict:
                self._raise_error(EXEC_HEADER_OFFLINE)
            elif time() - self._cmd_sent_at > 1.0:
                self._send_cmd(executor)
                self._cmd_retry += 1
                L.debug("Header cmd timeout, retry (%i)", self._update_retry)

        elif time() - self._lastupdate > 1.0:
            if not self._padding_cmd:
                self._handle_ping(executor)
                self._wait_update = True

    def _raise_error(self, *args):
        self._ready = False
        raise RuntimeError(*args)