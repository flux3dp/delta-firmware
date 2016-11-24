
from libc.stdlib cimport malloc, free
from libc.stdint cimport uint32_t
from libc.string cimport strncmp
from cpython cimport exc

cdef extern from "sys/socket.h":
    ssize_t send(int socket, const void *buffer, size_t length, int flags);

cdef extern from "../systime/systime.h":
    float monotonic_time()

cdef extern from "main_controller_misc.h":
    # misc.h
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

    int recvline(int sock_fd, RecvBuffer *buf, const char **endptr)
    int parse_dict(const char *begin, const char *terminator, object d)

    # main_controller_misc.h
    const int COMMAND_LENGTH
    unsigned int build_mainboard_command(char *buf, const char *cmd, size_t cmd_size, uint32_t lineno)
    unsigned int handle_ln(const char* buf, unsigned int length, CommandQueue *cmd_sent, CommandQueue *cmd_padding)
    uint32_t handle_ln_mismatch(const char *buf, unsigned int length, int sock_fd, CommandQueue *cmd_sent, CommandQueue *cmd_padding, uint32_t flag);
    uint32_t handle_checksum_mismatch(const char *buf, unsigned int length, int sock_fd, CommandQueue *cmd_sent, CommandQueue *cmd_padding, uint32_t flag);
    uint32_t resend(int sock_fd, CommandQueue *cmd_sent, uint32_t flag);


from collections import deque
import logging

from fluxmonitor.err_codes import EXEC_OPERATION_ERROR, EXEC_INTERNAL_ERROR,\
    EXEC_MAINBOARD_OFFLINE, EXEC_FILAMENT_RUNOUT, HARDWARE_ERROR, \
    EXEC_HOME_FAILED, EXEC_SENSOR_ERROR


cdef object L = logging.getLogger(__name__)

DEF MAX_COMMAND_RETRY = 3
DEF COMMAND_TIMEOUT = 0.4
cdef int FLAG_READY = 1
cdef int FLAG_ERROR = 2
cdef int FLAG_CLOSING = 4
cdef int FLAG_CLOSED = 8

cdef class MainController:
    # Number, from 0
    cdef public int _ln  # current sequence
    cdef readonly int _resend_inhibit

    # Communicate counter
    cdef public float send_timestamp
    cdef public unsigned int send_retry

    cdef readonly int _flags

    cdef readonly int bufsize

    cdef object callback_ready
    cdef object callback_msg_empty
    cdef object callback_msg_sendable
    cdef object callback_ctrl

    cdef int sock_fd
    cdef RecvBuffer recv_buffer
    cdef CommandQueue _cmd_sent
    cdef CommandQueue _cmd_padding

    cdef char *command_buffer

    def __init__(self, int sock_fd, unsigned int bufsize,
                 empty_callback=None, sendable_callback=None,
                 ctrl_callback=None):
        self.send_timestamp = -1
        self.send_retry = 0
        self._flags = 0

        init_command_queue(&(self._cmd_sent))
        init_command_queue(&(self._cmd_padding))

        self.sock_fd = sock_fd
        self.bufsize = bufsize
        self.command_buffer = <char*>malloc(COMMAND_LENGTH * bufsize)

        self.callback_msg_empty = empty_callback
        self.callback_msg_sendable = sendable_callback
        self.callback_ctrl = ctrl_callback

    def __del__(self):
        cdef CommandQueueItem *item
        while self._cmd_sent.length:
            item = pop_command_queue(&(self._cmd_sent))
            free(item)
        while self._cmd_padding.length:
            item = pop_command_queue(&(self._cmd_padding))
            free(item)
        free(self.command_buffer)

    cdef void send(self, const char *buf, size_t length):
        if(send(self.sock_fd, buf, length, 0) < 0):
            exc.PyErr_SetFromErrno(IOError)

    property ready:
        def __get__(self):
            return self._flags == FLAG_READY

    property buffered_cmd_size:
        def __get__(self):
            return self._cmd_sent.length + self._cmd_padding.length

    property queue_full:
        def __get__(self):
            return self.buffered_cmd_size >= self.bufsize

    #@property
    #def closed(self):
    #    return self.is_closed()

    #cdef inline int is_closed(self):
    #    if self._flags & FLAG_CLOSED > 0:
    #        return 1
    #    else:
    #        return 0

    def bootstrap(self, callback=None):
        if self._flags:
            if self._flags < FLAG_CLOSING:
                self._flags &= ~FLAG_ERROR
                if callback:
                    callback(self)
            else:
                raise SystemError(EXEC_OPERATION_ERROR)
        else:
            self.send_timestamp = monotonic_time()
            self.send("C1O\n", 4);
            self.callback_ready = callback

    def handle_recv(self):
        cdef const char* endptr
        cdef int ret
        while True:
            ret = recvline(self.sock_fd, &(self.recv_buffer), &endptr)

            if ret == -2:
                #TODO validate
                exc.PyErr_SetFromErrno(IOError)
            elif ret == -1:
                L.debug("Mainboard buffer full: %r", self.recv_buffer.b[:RECV_BUFFER_SIZE])
            elif ret == 0:
                pass
            elif ret > 0:
                self.handle_message(self.recv_buffer.b, endptr - self.recv_buffer.b)
                if ret == 2:
                    continue
            else:
                raise Exception("recvline return unknown ret: %i", ret)
            return

    cdef void handle_message(self, const char* buf, unsigned int length) except *:
        cdef char *anchor
        cdef uint32_t num_of_commands
        cdef CommandQueueItem *item

        if self._flags:
            if length > 3 and strncmp(buf, "LN ", 3) == 0:
                num_of_commands = handle_ln(buf, length, &(self._cmd_sent), &(self._cmd_padding))
                self._resend_inhibit = 0

                if num_of_commands + 1 == self.bufsize and self.callback_msg_sendable:
                    self.callback_msg_sendable(self)
                if num_of_commands == 0 and self.callback_msg_empty:
                    self.callback_msg_empty(self)

            elif length > 17 and strncmp(buf, "ER LINE_MISMATCH ", 17) == 0:
                self._resend_inhibit = handle_ln_mismatch(buf, length, self.sock_fd, &(self._cmd_sent), &(self._cmd_padding), self._resend_inhibit)

            elif length > 21 and strncmp(buf, "ER CHECKSUM_MISMATCH ", 21) == 0:
                self._resend_inhibit = handle_checksum_mismatch(buf, length, self.sock_fd, &(self._cmd_sent), &(self._cmd_padding), self._resend_inhibit)

            elif length > 20 and strncmp(buf, "CTRL FILAMENTRUNOUT ", 20) == 0:
                if self._flags & FLAG_ERROR == 0:
                    self._flags |= FLAG_ERROR
                    err = RuntimeError(EXEC_FILAMENT_RUNOUT, buf[20:length])
                    err.hw_error_code = 49
                    raise err
            elif length == 23 and strncmp(buf, "CTRL LINECHECK_DISABLED", 23) == 0:
                if self._flags & FLAG_CLOSING:
                    self._flags |= FLAG_CLOSED;
            elif length > 5 and strncmp(buf, "CTRL ", 5) == 0:
                if self.callback_ctrl:
                    self.callback_ctrl(self, buf[5:length])
            elif length > 5 and strncmp(buf, "DATA ", 5) == 0:
                if self.callback_ctrl:
                    self.callback_ctrl(self, buf[:length])
            elif length > 6 and strncmp(buf, "DEBUG ", 6) == 0:
                if self.callback_ctrl:
                    self.callback_ctrl(self, buf[:length])
            elif length == 13 and strncmp(buf, "ER G28_FAILED", 13) == 0:
                raise SystemError(HARDWARE_ERROR, EXEC_HOME_FAILED)
            elif length > 7 and strncmp(buf, "ER FSR ", 7) == 0:
                raise RuntimeError(HARDWARE_ERROR, EXEC_SENSOR_ERROR, "FSR",
                                   *(buf[7:length].split(" ")))
            elif length > 4 and strncmp(buf, "ER ", 3) == 0:
                raise SystemError(HARDWARE_ERROR, *(buf[3:length].split(" ")))
            elif length == 2 and strncmp(buf, "ok", 2) == 0:
                pass
            else:
                L.debug("Recv unknown mainboard message: %r", buf[:length])

        else:
            if length == 22 and strncmp(buf, "CTRL LINECHECK_ENABLED", 22) == 0:
                self._ln = 0
                self._flags |= FLAG_READY
                cb = self.callback_ready
                self.callback_ready = None
                if cb:
                    cb(self)
            elif length > 22 and strncmp(buf, "ER MISSING_LINENUMBER ", 22) == 0:
                L.warning("Mainboard linecheck already enabled")
                self.send_timestamp = monotonic_time()
                self.send("@DISABLE_LINECHECK\n", 19)
            elif length == 23 and strncmp(buf, "CTRL LINECHECK_DISABLED", 23) == 0:
                self.send_timestamp = monotonic_time()
                self.send("C1O\n", 4);
            else:
                L.info("Recv unknown mainboard message: %r", buf[:length])

    def send_cmd(self, unsigned char[] command, int raw=0):
        cdef char *buf
        cdef unsigned int size

        if raw:
            self.send(<const char *>command, len(command))
            return

        if self._flags and self._flags < FLAG_CLOSING:
            if self.buffered_cmd_size < self.bufsize:
                self._ln += 1
                buf = self.command_buffer + COMMAND_LENGTH * (self._ln % self.bufsize)
                size = build_mainboard_command(buf, <const char *>command, len(command), self._ln)
                if size < 0:
                    raise SystemError(EXEC_OPERATION_ERROR, "COMMAND_OVERFLOW")
                if not self._cmd_sent.length:
                    self.send_timestamp = monotonic_time()
                append_command_queue(&(self._cmd_sent), buf, size, self._ln)
                self.send(buf, size)
            else:
                raise RuntimeError(EXEC_OPERATION_ERROR, "BUF_FULL")
        else:
            raise RuntimeError(EXEC_OPERATION_ERROR, "NOT_READY")

    def patrol(self):
        if self._flags:
            if self._cmd_sent.length and monotonic_time() - self.send_timestamp > COMMAND_TIMEOUT:
                if self.send_retry >= MAX_COMMAND_RETRY:
                    raise SystemError(EXEC_MAINBOARD_OFFLINE)
                else:
                    self.send_timestamp = monotonic_time()
                    self.send_retry += 1
                    self._resend_inhibit = resend(self.sock_fd, &(self._cmd_sent), 0)
        else:
            if monotonic_time() - self.send_timestamp > COMMAND_TIMEOUT:
                if self.send_retry >= MAX_COMMAND_RETRY:
                    raise SystemError(EXEC_MAINBOARD_OFFLINE)
                else:
                    self.send_timestamp = monotonic_time()
                    self.send_retry += 1
                    self.send("C1O\n", 4)

    def close(self):
        if self._flags and self._flags < FLAG_CLOSING:
            send(self.sock_fd, "@DISABLE_LINECHECK\n", 19, 0)
            send(self.sock_fd, "X5S0\n", 5, 0)
            send(self.sock_fd, "G28+\n", 5, 0)
            self._flags |= FLAG_CLOSING;
