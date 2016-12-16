
from libc.stdlib cimport malloc, free
from libc.stdint cimport uint32_t
from libc.string cimport strncmp
from libc.math cimport isnan
from cpython cimport bool, exc

cdef extern from "sys/socket.h":
    ssize_t send(int socket, const void *buffer, size_t length, int flags);

cdef extern from "../systime/systime.h":
    float monotonic_time()

cdef extern from "misc.h":
    const int RECV_BUFFER_SIZE
    ctypedef struct RecvBuffer:
        char b[512];
        const char* begin;
        const char* end;
    ctypedef struct CommandQueueItem:
        char *buffer;
        size_t length;
    ctypedef struct CommandQueue:
        size_t length

    void init_command_queue(CommandQueue *q);
    void append_command_queue(CommandQueue *q, char *buf, size_t size, uint32_t lineno);
    CommandQueueItem* pop_command_queue(CommandQueue *q);
    void clear_command_queue(CommandQueue *q);

    unsigned int build_toolhead_command(char **buf, const char* fmt, ...)

    int recvline(int sock_fd, RecvBuffer *buf, const char **endptr)
    int validate_toolhead_message_1(const char *begin, const char *end);

    int parse_dict(const char *begin, const char *terminator, object d)


import logging

from fluxmonitor.err_codes import EXEC_HEAD_OFFLINE, EXEC_OPERATION_ERROR, \
    EXEC_TYPE_ERROR, EXEC_HEAD_ERROR, EXEC_HEAD_RESET, EXEC_UNKNOWN_HEAD, \
    FILE_BROKEN

DEF COMMAND_TIMEOUT = 0.6
DEF UPDATE_FREQUENCY = 0.8
DEF MAX_COMMAND_RETRY = 3

DEF ST_INIT = 0x00
DEF ST_BOOTING = 0x01
DEF ST_RUNNING = 0x08

cdef const char* NULL_TOOLHEAD_HELLO = "TYPE:N/A"
cdef MODULES_EXT = {}
cdef L = logging.getLogger(__name__)


cdef class HeadController:
    cdef int _st_flag

    cdef public uint32_t error_code

    cdef readonly object profile
    cdef readonly object status

    cdef bool updating
    cdef public float lastupdate

    cdef char* cmdbuf
    cdef unsigned int cmdbuf_size
    cdef public float send_timestamp
    cdef public unsigned int send_retry

    cdef CommandQueue command_queue

    cdef readonly str module_name
    cdef readonly object required_module

    cdef public object ext  # Extention object
    cdef object _ready_callback, _cmd_callback, _allset_callback, _msg_callback

    cdef int _sock_fd
    cdef RecvBuffer recv_buffer

    def __init__(self, int sock_fd, required_module=None, msg_callback=None):
        self._sock_fd = sock_fd
        self.required_module = required_module
        self._msg_callback = msg_callback
        self._st_flag = ST_INIT
        self.profile = {}
        self.status = {}

        init_command_queue(&(self.command_queue))
        self.recv_buffer.begin = self.recv_buffer.b
        self.recv_buffer.end = self.recv_buffer.b

        if required_module != "N/A" and required_module is not None:
            ext_klass = MODULES_EXT.get(required_module)
            if ext_klass:
                self.ext = ext_klass()
                self.ext.set_controller(self)
            else:
                raise SystemError(FILE_BROKEN, EXEC_HEAD_ERROR,
                                  EXEC_TYPE_ERROR, required_module)
        self.module_name = "N/A"

    def __del__(self):
        clear_command_queue(&(self.command_queue))
        if self.cmdbuf:
            free(self.cmdbuf)

    def bootstrap(self, callback=None):
        clear_command_queue(&(self.command_queue))
        if self.cmdbuf != NULL:
            free(self.cmdbuf)
            self.cmdbuf = NULL
            self.cmdbuf_size = 0

        self._st_flag = ST_BOOTING
        self.error_code = 0
        self.send_retry = 0
        self._send_hello()
        self._ready_callback = callback

    def recover(self, callback=None):
        if self._st_flag != ST_RUNNING:
            raise RuntimeError(EXEC_OPERATION_ERROR)

        if self.ext:
            self.ext.do_recover()
            if self.command_queue.length:
                self._cmd_callback = callback

                if not self.updating:
                    cmd_item = pop_command_queue(&(self.command_queue))
                    self.send_command(cmd_item.buffer, cmd_item.length)
                    free(cmd_item)
                return

        if callback:
            callback(self)

    def standby(self, callback=None):
        if self._st_flag != ST_RUNNING:
            raise RuntimeError(EXEC_OPERATION_ERROR)

        if self.ext:
            self.ext.do_standby()
            if self.command_queue.length:
                self._cmd_callback = callback

                if not self.updating:
                    cmd_item = pop_command_queue(&(self.command_queue))
                    self.send_command(cmd_item.buffer, cmd_item.length)
                    free(cmd_item)
                return

        if callback:
            callback(self)

    cpdef void reset(self):
        self._st_flag = ST_INIT
        self.module_name = None
        self.status = {"module": self.module_name}
        self.profile = {"TYPE": self.module_name}
        self.error_code = 0
        if self.required_module is None:
            self.ext = None

    def shutdown(self, callback=None):
        if self._st_flag != ST_RUNNING:
            raise RuntimeError(EXEC_OPERATION_ERROR)

        if self.ext:
            self.ext.do_shutdown()
            if self.command_queue.length:
                self._cmd_callback = callback

                if not self.updating:
                    cmd_item = pop_command_queue(&(self.command_queue))
                    self.send_command(cmd_item.buffer, cmd_item.length)
                    free(cmd_item)
                return

        if callback:
            callback(self)

    def handle_recv(self):
        cdef const char* endptr
        cdef int ret, size
        while True:
            ret = recvline(self._sock_fd, &(self.recv_buffer), &endptr)

            if ret == -2:
                exc.PyErr_SetFromErrno(IOError)
            elif ret == -1:
                L.debug("Toolhead buffer full: %r", self.recv_buffer.b[:RECV_BUFFER_SIZE])
            elif ret == 0:
                pass
            elif ret > 0:
                size = validate_toolhead_message_1(self.recv_buffer.b, endptr)
                if size > 0:
                    self.handle_message(self.recv_buffer.b + 2, size - 2)
                    if self._msg_callback:
                        self._msg_callback(self, self.recv_buffer.b[2:size - 2])
                else:
                    L.debug("Toolhead message error: %r", self.recv_buffer.b[:RECV_BUFFER_SIZE])
                if ret == 2:
                    continue
            else:
                raise Exception("recvline return unknown ret: %i", ret)
            return

    def patrol(self):
        cdef float t = monotonic_time()

        if (self._st_flag == ST_RUNNING and self.cmdbuf != NULL):
            # Check exec command
            if(t - self.send_timestamp > COMMAND_TIMEOUT):
                if(self.send_retry >= MAX_COMMAND_RETRY):
                    self._on_head_offline(HeadOfflineError)
                else:
                    self.send_retry += 1
                    self._send_command()

        elif self._st_flag == ST_RUNNING and self.updating:
            # Check ping
            if(t - self.send_timestamp > COMMAND_TIMEOUT):
                if self.send_retry >= MAX_COMMAND_RETRY and self.ext:
                    self._on_head_offline(HeadOfflineError)
                else:
                    self.send_retry += 1
                    self._send_ping()
        elif self._st_flag == ST_RUNNING and t - self.lastupdate > UPDATE_FREQUENCY:
            # Send ping
            self.send_retry = 0
            self.updating = True
            self._send_ping()

        elif self._st_flag == ST_BOOTING:
            # Check hello
            if(t - self.send_timestamp > COMMAND_TIMEOUT):
                if self.required_module == "N/A" or self.required_module == None:
                    self._on_ready()

                elif self.send_retry >= MAX_COMMAND_RETRY:
                    self._on_head_offline(HeadOfflineError)
                else:
                    self.send_retry += 1
                    self._send_hello()

    property ready:
        def __get__(self):
            return self._st_flag == ST_RUNNING

    property allset:
        def __get__(self):
            return self.ext.allset() if self.ext else True

    cpdef sendable(self):
        return self._st_flag > ST_BOOTING and self.cmdbuf == NULL

    cdef void handle_message(self, const char* buf, unsigned int length) except *:
        cdef CommandQueueItem* cmd_item
        if length > 8 and strncmp("OK PONG ", buf, 8) == 0:
            self.on_update(buf + 8, buf + length)
            return
        elif length > 9 and strncmp("OK HELLO ", buf, 9) == 0:
            self.on_hello(buf + 9, buf + length)
            return
        elif length > 3:
            if strncmp("OK ", buf, 3) == 0:
                free(self.cmdbuf)
                self.cmdbuf = NULL

                if self.ext:
                    self.ext.on_response(buf[3:length])

                cmd_item = pop_command_queue(&(self.command_queue))
                if cmd_item:
                    self.send_command(cmd_item.buffer, cmd_item.length)
                    free(cmd_item)
                else:
                    if self._cmd_callback:
                        cb = self._cmd_callback
                        self._cmd_callback = None
                        cb(self)

                return
            elif strncmp("ER ", buf, 3) == 0:
                raise RuntimeError(EXEC_HEAD_ERROR, *(buf[:length].split(" ")))

        L.debug("Toolhead recv unknown message: %r", buf[:length])

    cdef void on_hello(self, const char* begin, const char* terminator) except *:
        cdef CommandQueueItem* cmd_item

        try:
            parse_dict(begin, terminator, self.profile)
            info = self.profile
            module_type = info.get("TYPE", "UNKNOWN")

            if self.ext:
                self.ext.on_hello(info)
                self.module_name = module_type
            else:
                if self.required_module == "N/A":
                    raise HeadTypeError("N/A", module_type)
                else:
                    ext_klass = MODULES_EXT.get(module_type.split("/")[0])
                    if ext_klass:
                        self.ext = ext_klass()
                        self.ext.set_controller(self)
                        self.ext.on_hello(info)
                    else:
                        raise RuntimeError(EXEC_UNKNOWN_HEAD, module_type)

                self.module_name = module_type
            self._on_ready()

        except:
            self._st_flag = ST_INIT
            raise

    cdef void on_update(self, const char* begin, const char *terminator) except *:
        cdef int er = -1
        cdef CommandQueueItem *cmd_item;

        self.updating = False
        self.lastupdate = monotonic_time()
        parse_dict(begin, terminator, self.status)
        status = self.status

        try:
            s_er = status.pop("ER", None)
            if s_er: er = int(s_er)
        except ValueError:
            L.error("Toolhead ER flag error: %r", s_er)

        self.error_code |= er
        if er == 0 or self._st_flag == ST_INIT:
            pass
        elif er & 4:
            if er & 1024:
                self._on_head_offline(HeadCrashError)
            else:
                self._on_head_offline(HeadResetError)

        if self.ext:
            self.ext.on_update(status)
        else:
            L.error("No ext for update")

        cmd_item = pop_command_queue(&(self.command_queue))
        if cmd_item:
            self.send_command(cmd_item.buffer, cmd_item.length)
            free(cmd_item)

        if self._allset_callback and self.ext and self.ext.allset():
            cb = self._allset_callback
            self._allset_callback = None
            cb(self)

    cdef void _send_command(self) except *:
        self.send_timestamp = monotonic_time()
        if(send(self._sock_fd, self.cmdbuf, self.cmdbuf_size, 0) < 0):
            exc.PyErr_SetFromErrno(IOError)

    cdef void _send_hello(self) except *:
        self.send_timestamp = monotonic_time()
        if(send(self._sock_fd, "1 HELLO *115\n", 13, 0) < 0):
            exc.PyErr_SetFromErrno(IOError)

    cdef void _send_ping(self) except *:
        self.send_timestamp = monotonic_time()
        if(send(self._sock_fd, "1 PING *33\n", 11, 0) < 0):
            exc.PyErr_SetFromErrno(IOError)

    cdef void send_command(self, char *buf, unsigned int size) except *:
        if self.sendable():
            self.cmdbuf = buf
            self.cmdbuf_size = size
            self._send_command()
        else:
            raise RuntimeError(EXEC_OPERATION_ERROR, "RESOURCE_BUSY",
                               self.cmdbuf[:self.cmdbuf_size])

    def set_command_callback(self, callback=None):
        self._cmd_callback = callback

    def set_allset_callback(self, callback=None):
        self._allset_callback = callback

    cdef void _on_ready(self) except *:
        self._st_flag = ST_RUNNING
        self.status["module"] = self.module_name
        if self._ready_callback:
            try:
                self._ready_callback(self)
            finally:
                self._ready_callback = None

    cdef void _on_head_offline(self, error_klass) except *:
        self.reset()
        raise error_klass()


cdef class ExtruderExt:
    cdef HeadController controller
    cdef double _fanspeed
    cdef int _req_num_of_extruder, _num_of_extruder
    cdef double _req_max_temperature, _max_temperature
    cdef double* _temperatures

    def __init__(self, int num_of_extruder=1, double max_temperature=235.0):
        cdef double nan = float("NaN")

        self._req_num_of_extruder = num_of_extruder
        self._req_max_temperature = max_temperature

        self._temperatures = <double*>malloc(num_of_extruder * sizeof(double))
        self._fanspeed = nan

        cdef int i
        for i from 0 < i < num_of_extruder:
            self._temperatures[i] = nan

    def __del__(self):
        free(self._temperatures)

    def set_controller(self, HeadController c):
        self.controller = c

    # REQ
    def on_hello(self, info):
        m = info.get("TYPE", "UNKNOW")
        if m != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", m)
        try:
            val = int(info.pop("EXTRUDER", "-1"))
            if val >= self._req_num_of_extruder:
                info["EXTRUDER"] = val
            else:
                raise HeadError(EXEC_HEAD_ERROR, "SPEC_ERROR", "EXTRUDER")
        except ValueError:
            raise HeadError(EXEC_HEAD_ERROR, "SPEC_ERROR", "EXTRUDER")

    # REQ
    def on_update(self, status):
        pass

    # REQ
    def on_response(self, message):
        pass

    # REQ
    def do_recover(self):
        cdef int i
        cdef char *buf
        cdef unsigned int size

        if not isnan(self._fanspeed):
            size = build_toolhead_command(&buf, "F:%i S:%i", 0, <int>(self._fanspeed * 255))
            append_command_queue(&(self.controller.command_queue), buf, size, 0)
        for i from 0 <= i < self._req_num_of_extruder:
            if not isnan(self._temperatures[i]):
                size = build_toolhead_command(&buf, "H:%i T:%.1f", i, self._temperatures[i])
                append_command_queue(&(self.controller.command_queue), buf, size, 0)

    #REQ
    def do_standby(self):
        cdef unsigned int size
        cdef char *buf
        cdef int i
        size = build_toolhead_command(&buf, "F:0 S:0")
        append_command_queue(&(self.controller.command_queue), buf, size, 0)
        for i from 0 <= i < self._req_num_of_extruder:
            size = build_toolhead_command(&buf, "H:%i T:%.1f", i, 0)
            append_command_queue(&(self.controller.command_queue), buf, size, 0)

    #REQ
    def do_shutdown(self):
        cdef unsigned int size
        cdef char *buf
        cdef int i
        self._fanspeed = 0
        for i from 0 <= i < self._req_num_of_extruder:
            self._temperatures[i] = 0
        self.do_recover()

    def set_heater(self, int heater_id, double temperature):
        if temperature < 0:
            raise SystemError(EXEC_OPERATION_ERROR, "BAD_TEMPERATURE",
                               str(temperature))
        elif temperature > 280:
            raise SystemError(EXEC_OPERATION_ERROR, "BAD_TEMPERATURE",
                              str(temperature))

        self._temperatures[heater_id] = temperature
        cdef char* buf
        cdef int size = build_toolhead_command(&buf, "H:%i T:%.1f", heater_id, temperature)
        self.controller.send_command(buf, size)

    def set_fanspeed(self, int fan_id, double fan_speed):
        self._fanspeed = f = max(min(1.0, fan_speed), 0)

        cdef char* buf
        cdef int size = build_toolhead_command(&buf, "F:%i S:%i", fan_id, <int>(fan_speed * 255))
        self.controller.send_command(buf, size)

    def allset(self):
        cdef tuple rt = self.controller.status.get("rt", ())
        if len(rt) < self._req_num_of_extruder:
            return False

        for i from 0 <= i < self._req_num_of_extruder:
            if self._temperatures[i] > 0 and \
                    abs(self._temperatures[i] - rt[i]) > 3:
                return False
        return True


cdef class LaserExt:
    cdef HeadController controller

    def set_controller(self, HeadController c):
        self.controller = c

    def on_hello(self, info):
        m = info.get("TYPE", "UNKNOW")
        if m != "LASER":
            raise HeadTypeError("LASER", m)

    def on_update(self, status): pass
    def do_recover(self): pass
    def do_standby(self): pass
    def do_shutdown(self): pass
    def allset(self): return True


cdef class UserExt:
    def set_controller(self, HeadController c):
        self.controller = c

    def on_hello(self, info):
        m = info.get("TYPE", "UNKNOW")
        if not m.startswith("USER/"):
            raise HeadTypeError("USER", m)

    def on_update(self, status): pass
    def do_recover(self): pass
    def do_standby(self): pass
    def do_shutdown(self): pass
    def allset(self): return True

    def send_raw_command(self, cmd, HeadController controller):
        cdef char *buf
        cdef unsigned int size
        size = build_toolhead_command(&buf, cmd)
        controller.send_command(buf, size)


MODULES_EXT["EXTRUDER"] = ExtruderExt
MODULES_EXT["LASER"] = LaserExt
MODULES_EXT["USER"] = UserExt


class HeadError(RuntimeError):
    pass


class HeadOfflineError(HeadError):
    hw_error_code = 51

    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_OFFLINE)


class HeadResetError(HeadError):
    hw_error_code = 51

    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_RESET)


class HeadCrashError(HeadError):
    hw_error_code = 51

    def __init__(self):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_HEAD_RESET)


class HeadTypeError(HeadError):
    hw_error_code = 53

    def __init__(self, expected_type, got_type):
        RuntimeError.__init__(self, EXEC_HEAD_ERROR, EXEC_TYPE_ERROR,
                              expected_type, got_type)
