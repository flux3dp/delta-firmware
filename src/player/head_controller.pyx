

from libc.stdio cimport sscanf
from cpython cimport bool

cdef extern from "systime.c":
    float monotonic_time()


from shlex import split as shlex_split
import logging

from fluxmonitor.err_codes import EXEC_HEAD_OFFLINE, EXEC_OPERATION_ERROR, \
    EXEC_TYPE_ERROR, EXEC_HEAD_ERROR, EXEC_NEED_REMOVE_HEAD, \
    EXEC_UNKNOWN_REQUIRED_HEAD_TYPE, EXEC_HEAD_RESET, EXEC_HEAD_CALIBRATING, \
    EXEC_HEAD_SHAKE, EXEC_HEAD_TILT, HARDWARE_FAILURE, EXEC_HEAD_FAN_FAILURE, \
    EXEC_UNKNOWN_HEAD, FILE_BROKEN, UNKNOWN_COMMAND


DEF MAX_COMMAND_RETRY = 3
DEF MAX_PING_RETRY = 3
DEF HELLO_CMD = "1 HELLO *115\n"
DEF PING_CMD = "1 PING *33\n"
cdef MODULES_EXT = {}
cdef L = logging.getLogger(__name__)


def create_chksum_cmd(fmt, *args):
    cdef int s = 0
    cmd = fmt % args
    for c in cmd:
        s ^= ord(c)
    s ^= 32
    return "%s *%i\n" % (cmd, s)


cdef class HeadController:
    cdef object _module  # String
    cdef object _required_module  # String
    cdef object _padding_cmd  # String
    cdef object _recover_queue  # Python array of string
    cdef object _ext  # Extention object

    cdef object _ready_callback
    cdef object _cmd_callback
    cdef object _allset_callback

    cdef int _ready
    cdef bool _wait_update

    cdef public float _timer
    cdef public float _cmd_sent_at
    cdef public int _cmd_retry

    cdef public float _lastupdate
    cdef public int _update_retry

    cdef unsigned int _error_level

    def __init__(self, executor, ready_callback, required_module=None,
                 error_level=255):
        self._error_level = error_level
        self._required_module = required_module
        self._ready_callback = ready_callback

        if required_module != "N/A" and required_module is not None:
            ext_klass = MODULES_EXT.get(required_module)
            if ext_klass:
                self._ext = ext_klass()
            else:
                raise SystemError(FILE_BROKEN, EXEC_HEAD_ERROR,
                                  EXEC_TYPE_ERROR, required_module)

        self._module = "N/A"
        self.bootstrap(executor)

    def bootstrap(self, executor):
        self._ready = 1
        self._cmd_sent_at = 0
        self._cmd_retry = 0
        self._padding_cmd = None
        self._cmd_callback = None
        self._allset_callback = None

        self._lastupdate = 0
        self._update_retry = 0
        self._wait_update = False

        if self._ext:
            self._recover_queue = self._ext.bootstrap_commands()
        else:
            self._recover_queue = []

        self._padding_cmd = HELLO_CMD
        self._send_cmd(executor)

    @property
    def ready(self):
        return self._ready == 8

    @property
    def is_busy(self):
        return self._padding_cmd is not None

    @property
    def module(self):
        return self._module

    def status(self):
        if self._ready == 8 and self._ext:
            return self._ext.status()
        else:
            return {"module": "N/A"}

    def _on_head_hello(self, msg):
        try:
            module_info = {}
            for param in shlex_split(msg):
                sparam = param.split(":", 1)
                if len(sparam) == 2:
                    module_info[sparam[0]] = sparam[1]

            module_type = module_info.get("TYPE", "UNKNOWN")

            if self._ext:
                self._ext.hello(**module_info)
            else:
                if self._required_module == "N/A":
                    raise RuntimeError(EXEC_NEED_REMOVE_HEAD)
                else:
                    ext_klass = MODULES_EXT.get(module_type)
                    if ext_klass:
                        self._ext = ext_klass()
                    else:
                        raise RuntimeError(EXEC_UNKNOWN_HEAD, module_type)

                self._module = module_info.get("TYPE", "UNKNOWN")
        except Exception:
            self._ready = 0
            raise

    def _on_head_offline(self, error_klass):
        self._module = "N/A"
        self._ready = 0
        if self._required_module is None:
            self._ext = None
        raise error_klass()

    def _on_ready(self):
        self._ready = 8
        if self._ready_callback:
            self._ready_callback(self)

    def wait_allset(self, callback):
        self._allset_callback = callback

    def on_message(self, const unsigned char *raw_message, executor):
        cdef int val
        cdef unsigned char s = 0;
        cdef unsigned char *ptr = raw_message
        if raw_message[0] == '1' and raw_message[1] == ' ':
            while True:
                if ptr[0] == '*':
                    sscanf(<const char *>(ptr + 1), "%d", &val)
                    if val == s:
                        self.handle_message(raw_message[2:ptr - raw_message],
                                            executor)
                    return
                elif ptr[0] == 0:
                    L.warn("Drop message %s", raw_message)
                    return
                else:
                    s ^= ptr[0]
                    ptr += 1

    cdef inline handle_message(self, msg, executor):
        if self._ready == 8:
            if msg.startswith("OK PONG "):
                self._handle_pong(msg)
                if self._padding_cmd:
                    self._send_cmd(executor)
            elif self._parse_cmd_response(msg, executor):
                pass
            elif self._ext.on_message(msg):
                pass
            else:
                L.info("RECV_UH: '%s'", msg)
        elif self._ready == 4:
            if self._parse_cmd_response(msg, executor):
                if self._recover_queue:
                    self._padding_cmd = self._recover_queue.pop(0)
                    self._send_cmd(executor)
                else:
                    self._on_ready()
            else:
                L.info("GOT: '%s' (ready=%i)", msg, self._ready)
        elif self._ready == 2:
            if msg.startswith("OK PONG "):
                if self._handle_pong(msg) == 0:
                    self._padding_cmd = None
                    self._cmd_retry = self._cmd_sent_at = 0
                    if self._recover_queue:
                        self._ready = 4
                        self._padding_cmd = self._recover_queue.pop(0)
                        self._send_cmd(executor)
                    else:
                        self._on_ready()
                else:
                    if monotonic_time() - self._timer > 9:
                        self._ready = 4
                        self._handle_pong(msg)
                    else:
                        self._padding_cmd = PING_CMD
                        self._send_cmd(executor)
            else:
                L.info("GOT: '%s' (ready=%i)", msg, self._ready)
        elif self._ready == 1:
            if self._padding_cmd is HELLO_CMD:
                if msg.startswith("OK HELLO "):
                    self._on_head_hello(msg[9:])
                    self._ready = 2
                    self._padding_cmd = PING_CMD
                    self._timer = monotonic_time()
                    self._cmd_retry = self._cmd_sent_at = 0
                    self._send_cmd(executor)
                else:
                    L.info("GOT: '%s' (ready=%i)", msg, self._ready)
        else:
            L.info("GOT: '%s' (ready=%i)", msg, self._ready)

    def send_cmd(self, cmd, executor, complete_callback=None,
                 allset_callback=None):
        if self.is_busy:
            self._raise_error(EXEC_OPERATION_ERROR,
                              "BUSY: %s" % self._padding_cmd)

        padding_cmd = self._ext.generate_command(cmd)
        if padding_cmd:
            self._padding_cmd = padding_cmd
            self._send_cmd(executor)
            self._cmd_callback = complete_callback
            self.wait_allset(allset_callback)
        else:
            L.error("Got unknow command: %s", cmd)
            raise SystemError(UNKNOWN_COMMAND, "HEAD_MESSAGE")

    def _send_cmd(self, executor):
        if not self._wait_update:
            self._cmd_sent_at = monotonic_time()
            executor.send_headboard(self._padding_cmd)

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
            raise RuntimeError(EXEC_HEAD_ERROR, *err)

        else:
            return False

    cdef inline int _handle_ping(self, executor) except *:
        executor.send_headboard(PING_CMD)
        if self._ext is not None:
            self._wait_update = True
        self._lastupdate = monotonic_time()
        return 0

    cdef inline int _handle_pong(self, msg) except *:
        cdef int er = -1
        self._update_retry = 0
        self._wait_update = False
        self._lastupdate = monotonic_time()

        for param in shlex_split(msg[8:]):
            status = param.split(":", 1)
            if len(status) != 2:
                # params should be "KEY:VALUE"
                L.error("Unknow pong param: %s", param)

            elif status[0] == "ER":
                try:
                    er = int(status[1])
                except ValueError:
                        L.error("Head er flag failed")
                        self._raise_error(EXEC_HEAD_ERROR, "ER_ERROR")

                if er == 0 or self._ready == 0:
                    pass
                elif er & 4:
                    self._on_head_offline(HeadResetError)
                elif self._ready >= 4 and er & self._error_level & ~7:
                    self._ready = 0
                    if er & 8:
                        raise HeadCalibratingError()
                    if er & 16:
                        raise HeadShakeError()
                    if er & 32:
                        raise HeadTiltError()
                    if er & 64:
                        raise HeadHardwareError()
                    if er & 128:
                        raise HeadFanError()
                    raise HeadError(EXEC_HEAD_ERROR, "?")

            else:
                self._ext.update_status(*status)
                if self._allset_callback and self._ext.all_set():
                    try:
                        self._allset_callback(self)
                    finally:
                        self._allset_callback = None
        return er

    def patrol(self, executor):
        cdef float t = monotonic_time()

        if self._wait_update:
            if self._update_retry > MAX_PING_RETRY and self._ready:
                self._on_head_offline(HeadOfflineError)
            if t - self._lastupdate > 0.4:
                self._update_retry += 1 if self._ready else 0
                self._handle_ping(executor)
                L.debug("Header ping timeout, retry (%i)", self._update_retry)

        elif t - self._lastupdate > 0.4:
            if not self._padding_cmd:
                self._handle_ping(executor)

        if self._ready and self._padding_cmd:
            if self._cmd_retry > MAX_COMMAND_RETRY and self._ready:
                self._on_head_offline(HeadOfflineError)
            elif t - self._cmd_sent_at > 0.8:
                if self._ext:
                    self._send_cmd(executor)
                    self._cmd_retry += 1 if self._ready else 0
                    L.debug("Header cmd timeout, retry (%i)", self._cmd_retry)
                else:
                    if self._padding_cmd == HELLO_CMD:
                        self._padding_cmd = None
                        self._on_ready()
                    else:
                        SystemError("Bad logic")

    def _raise_error(self, *args):
        raise RuntimeError(*args)


class BaseExt(object):
    def __init__(self, **spec):
        self.spec = spec

    def bootstrap_commands(self):
        return []

    def hello(self, **kw):
        self.id = kw.get("ID")
        self.vendor = kw.get("VENDOR")
        self.version = kw.get("VERSION")

    def generate_command(self, cmd):
        pass

    def update_status(self, key, value):
        pass

    def on_message(self, message):
        return False

    def all_set(self):
        return True


class ExtruderExt(BaseExt):
    _fanspeed = None
    _temperatures = None
    _current_temp = None

    def __init__(self):
        self._fanspeed = [0]
        self._temperatures = [float("NaN")]
        self._current_temp = [float("NaN")]

    def hello(self, **kw):
        m = kw.get("TYPE", "UNKNOW")
        if m != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", m)
        super(ExtruderExt, self).hello(**kw)

    def bootstrap_commands(self):
        cmds = []
        if self._fanspeed[0] >= 0:
            cmds.append(
                create_chksum_cmd("1 F:%i S:%i", 0, self._fanspeed[0] * 255))
        if self._temperatures[0] > 0:
            cmds.append(
                create_chksum_cmd("1 H:%i T:%.1f", 0, self._temperatures[0]))
        return cmds

    def status(self):
        return {
            "module": "EXTRUDER",
            "tt": (self._temperatures[0], ),
            "rt": (self._current_temp[0], ),
            "tf": (self._fanspeed[0], )
        }

    def set_heater(self, int heater_id, float temperature):
        if temperature < 5:
            raise RuntimeError(EXEC_OPERATION_ERROR, "BAD TEMP")
        elif temperature > 280:
            raise SystemError(EXEC_OPERATION_ERROR, "BAD TEMP")

        self._temperatures[0] = temperature
        return create_chksum_cmd("1 H:%i T:%.1f", heater_id, temperature)

    def set_fanspeed(self, int fan_id, float fan_speed):
        self._fanspeed[fan_id] = f = max(min(1.0, fan_speed), 0)
        return create_chksum_cmd("1 F:%i S:%i", fan_id, f * 255)

    def generate_command(self, cmd):
        if cmd.startswith("H"):
            target_temp = float(cmd[1:])
            return self.set_heater(0, target_temp)
        elif cmd.startswith("F"):
            target_speed = float(cmd[1:])
            return self.set_fanspeed(0, target_speed)
        else:
            return

    def update_status(self, key, value):
        if key == "RT":
            self._current_temp[0] = float(value)

    def on_message(self, message):
        return False

    def all_set(self):
        if self._temperatures[0] > 0:
            if abs(self._temperatures[0] - self._current_temp[0]) < 3:
                return True
            else:
                return False
        return True


class LaserExt(BaseExt):
    def hello(self, **kw):
        m = kw.get("TYPE", "UNKNOW")
        if m != "LASER":
            raise HeadTypeError("LASER", m)
        super(LaserExt, self).hello(**kw)

    def status(self):
        return {"module": "LASER",}


MODULES_EXT["EXTRUDER"] = ExtruderExt
MODULES_EXT["LASER"] = LaserExt


class HeadError(RuntimeError):
    pass


class HeadOfflineError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_OFFLINE)


class HeadResetError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_RESET)


class HeadTypeError(HeadError):
    def __init__(self, expected_type, got_type):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_TYPE_ERROR,
                              expected_type, got_type)


class HeadCalibratingError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_CALIBRATING)


class HeadShakeError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_SHAKE)


class HeadTiltError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_TILT)


class HeadHardwareError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, HARDWARE_FAILURE)


class HeadFanError(HeadError):
    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_FAN_FAILURE)

