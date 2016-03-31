
from libc.stdio cimport snprintf, sscanf
from libc.string cimport strncmp

cdef extern from "../systime/systime.h":
    float monotonic_time()

cdef extern from "misc.c":
    object create_cmd(int, const char*)


from collections import deque
import logging

from fluxmonitor.err_codes import EXEC_OPERATION_ERROR, EXEC_INTERNAL_ERROR,\
    EXEC_MAINBOARD_OFFLINE, EXEC_FILAMENT_RUNOUT, HARDWARE_ERROR, \
    EXEC_HOME_FAILED


cdef object L = logging.getLogger(__name__)

cdef int FLAG_READY = 1
cdef int FLAG_ERROR = 2
cdef int FLAG_CLOSED = 4


cdef inline object send_cmd(object executor, int lineno, const char* cmd):
    executor.send_mainboard(create_cmd(lineno, cmd))


cdef class MainController:
    # Number, from 0
    cdef public int _ln  # current sequence
    cdef public int _ln_ack  # Mainboard confirmd sequence

    # Communicate counter
    cdef public float _last_recv_ts  # Timestemp: last recive "LN x" message
    cdef public int _resend_counter  # Resend counter

    cdef public int _flags

    cdef public int _retry_ttl

    # Tuple: (ttl(int), time(float), ln(int))
    cdef object _inhibit_resend

    cdef int _bufsize

    cdef public object _cmd_sent
    cdef public object _cmd_padding

    cdef public object callback_ready
    cdef public object callback_msg_empty
    cdef public object callback_msg_sendable

    def __init__(self, executor, bufsize=16, ready_callback=None,
                 msg_empty_callback=None, msg_sendable_callback=None,
                 retry_ttl=3):
        self._retry_ttl = retry_ttl
        self._last_recv_ts = -1
        self._resend_counter = 0
        self._flags = 0

        self._cmd_sent = deque()
        self._cmd_padding = deque()
        self.callback_ready = ready_callback
        self.callback_msg_empty = msg_empty_callback
        self.callback_msg_sendable = msg_sendable_callback

        self._bufsize = bufsize

        self._last_recv_ts = monotonic_time()
        executor.send_mainboard("C1O\n")

    @property
    def ready(self):
        return self._flags == FLAG_READY

    @property
    def closed(self):
        return self.is_closed()

    cdef inline int is_closed(self):
        if self._flags & FLAG_CLOSED > 0:
            return 1
        else:
            return 0

    @property
    def buffered_cmd_size(self):
        return len(self._cmd_sent) + len(self._cmd_padding)

    @property
    def bufsize(self):
        return self._bufsize

    @property
    def queue_full(self):
        return self.buffered_cmd_size >= self._bufsize

    @bufsize.setter
    def bufsize(self, val):
        if val < 1:
            raise ValueError("bufsize must > 0")
        elif val > 16:
            raise ValueError("bufsize must <= 16")
        else:
            self._bufsize = val

    cpdef _process_init(self, const char* msg, object executor):
        cdef int ln
        if strncmp("CTRL LINECHECK_ENABLED", msg, 23) == 0:
            self._ln = 0
            self._ln_ack = 0
            self._flags |= FLAG_READY
            self.callback_ready(self)

        elif strncmp("ER MISSING_LINENUMBER ", msg, 22) == 0:
            L.error("Mainboard linecheck already enabled")
            # Try re-enbale line check
            if sscanf(msg + 22, "%d", &ln) == 1:
                send_cmd(executor, ln, "C1F")
        elif strncmp("CTRL LINECHECK_DISABLED", msg, 24) == 0:
            executor.send_mainboard("C1O\n")
        else:
            L.debug("Recv unknow msg: '%s'", msg)

    def bootstrap(self, executor):
        L.info("MAIN BOOTSTRAP")
        if self._flags == FLAG_READY:
            self.callback_ready(self)
        elif self._flags == (FLAG_READY + FLAG_ERROR):
            self._flags = FLAG_READY
            self.callback_ready(self)
        else:
            raise SystemError("BAD_LOGIC", "MBF_%i" % self._flags)

    def remove_complete_command(self, cmd=None):
        self._cmd_padding.popleft()

        if self.buffered_cmd_size + 1 == self._bufsize and \
           self.callback_msg_sendable:
            self.callback_msg_sendable(self)
        if self.buffered_cmd_size == 0 and self.callback_msg_empty:
            self.callback_msg_empty(self)

    def on_message(self, msg, executor):
        if self._flags & FLAG_READY:
            if msg.startswith("LN "):
                recv_ln, cmd_in_queue = (int(x) for x in msg.split(" ", 2)[1:])
                self._last_recv_ts = monotonic_time()
                self._resend_counter = 0

                while self._ln_ack < recv_ln:
                    cmd = self._cmd_sent.popleft()
                    self._cmd_padding.append(cmd)
                    self._ln_ack += 1

                while len(self._cmd_padding) > cmd_in_queue:
                    self.remove_complete_command()

            elif msg.startswith("ER LINE_MISMATCH "):
                correct_ln, trigger_ln = (int(v) for v in msg[17:].split(" "))
                if correct_ln < trigger_ln:
                    ttl = -2
                    if not self._resend_cmd_from(correct_ln, executor,
                                                 ttl_offset=ttl):
                        raise SystemError(EXEC_INTERNAL_ERROR,
                                          "IMPOSSIBLE_SYNC_LN")

            elif msg.startswith("ER CHECKSUM_MISMATCH "):
                err_ln, trigger_ln = (int(v) for v in msg[21:].split(" "))
                ttl = err_ln - trigger_ln
                if not self._resend_cmd_from(err_ln, executor,
                                             ttl_offset=ttl):
                    raise SystemError(EXEC_INTERNAL_ERROR,
                                      "IMPOSSIBLE_SYNC_LN")

            elif msg.startswith("CTRL FILAMENTRUNOUT "):
                if self._flags & FLAG_ERROR == 0:
                    self._flags |= FLAG_ERROR
                    err = RuntimeError(EXEC_FILAMENT_RUNOUT, msg.split(" ")[2])
                    err.hw_error_code = 49
                    raise err

            elif msg == "CTRL LINECHECK_DISABLED":
                executor.send_mainboard(b"C1O\n")

            elif msg == "CTRL STASH":
                pass

            elif msg == "CTRL STASH_POP":
                pass

            elif msg == "ok":
                pass

            elif msg == "ER G28_FAILED":
                raise SystemError(HARDWARE_ERROR, EXEC_HOME_FAILED)

            else:
                if msg.startswith("ER "):
                    raise SystemError(HARDWARE_ERROR, *(msg.split(" ")[1:]))

                L.debug("Unhandle MB MSG: %s" % msg)
        elif not self.closed:
            self._process_init(msg, executor)

    cpdef object create_cmd(self, int lineno, const char* cmd):
        return create_cmd(lineno, cmd)

    def _resend_cmd_from(self, lineno, executor, ttl_offset):
        if lineno < self._ln_ack:
            return True

        if self._inhibit_resend:
            ttl, ts, i_ln = self._inhibit_resend
            if i_ln == lineno and monotonic_time() - ts < 0.3 and ttl > 0:
                self._inhibit_resend = (ttl - 1, ts, i_ln)
                return True  # inhibit, quit resend
            else:
                # inhibit avoid (timeout)
                self._inhibit_resend = None

        while self._cmd_sent:
            cmdline = self._cmd_sent[0]
            if cmdline[0] < lineno:
                self._ln_ack = cmdline[0]
                self._cmd_sent.popleft()
                self._cmd_padding.append(cmdline)
            elif cmdline[0] == lineno:
                ttl = ttl_offset

                for cmdline in self._cmd_sent:
                    send_cmd(executor, cmdline[0], cmdline[1])
                    ttl += 1

                if ttl > 0:
                    self._inhibit_resend = (ttl, monotonic_time(), lineno)

                return True
            else:
                return False
        return False

    def send_cmd(self, cmd, executor, force=False):
        if self._flags & FLAG_READY:
            if self.buffered_cmd_size < self._bufsize or force:
                self._ln += 1
                send_cmd(executor, self._ln, cmd)
                if not self._cmd_sent:
                    self._last_recv_ts = monotonic_time()
                self._cmd_sent.append((self._ln, cmd))
            else:
                raise RuntimeError(EXEC_OPERATION_ERROR, "BUF_FULL")
        else:
            raise RuntimeError(EXEC_OPERATION_ERROR, "NOT_READY")

    def on_mainboard_dead(self):
        self._flags &= ~FLAG_READY
        self._flags |= FLAG_CLOSED
        raise SystemError(EXEC_MAINBOARD_OFFLINE)

    def close(self, executor):
        if self._flags & FLAG_READY:
            executor.send_mainboard("@DISABLE_LINECHECK\n")
            executor.send_mainboard("G28+\n")
            executor.send_mainboard("X5S0\n")
            self._flags &= ~FLAG_READY
            self._flags |= FLAG_CLOSED

    def patrol(self, executor):
        if not self._flags & FLAG_READY and not self.is_closed():
            if monotonic_time() - self._last_recv_ts > 1.0:
                self._resend_counter += 1
                if self._resend_counter > self._retry_ttl:
                    L.error("Mainboard no response, restart it")
                    self.on_mainboard_dead()

                self._last_recv_ts = monotonic_time()
                # Resend, let ttl_offset takes no effect
                executor.send_mainboard("C1O\n")

        if self._cmd_sent:
            if self._resend_counter >= self._retry_ttl:
                L.error("Mainboard no response, restart it (%i)",
                        self._resend_counter)
                self.on_mainboard_dead()

            if monotonic_time() - self._last_recv_ts > 3.0:
                self._last_recv_ts = monotonic_time()
                self._resend_counter += 1
                # Resend, let ttl_offset takes no effect
                self._resend_cmd_from(self._ln_ack + 1, executor,
                                      ttl_offset=-128)
