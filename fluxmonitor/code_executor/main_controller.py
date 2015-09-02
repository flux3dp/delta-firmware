
from collections import deque
from time import time
import logging
import socket

L = logging.getLogger(__name__)

from fluxmonitor.err_codes import EXEC_OPERATION_ERROR, EXEC_INTERNAL_ERROR,\
    EXEC_MAINBOARD_OFFLINE
from fluxmonitor.config import uart_config


class MainController(object):
    # Number, from 0
    _ln = None  # current sequence
    _ln_ack = None  # Mainboard confirmd sequence

    # Communicate counter
    _last_recv_ts = -1  # Timestemp: last recive "LN x" message
    _resend_counter = 0  # Resend counter

    # Booean
    _ready = False
    # Callable object
    _callback_ready = None
    # Tuple: (ttl(int), time(float), ln(int))
    _inhibit_resend = None

    _bufsize = None

    def __init__(self, executor, bufsize=16, ready_callback=None,
                 msg_empty_callback=None, msg_sendable_callback=None):
        self._cmd_sent = deque()
        self._cmd_padding = deque()
        self.callback_ready = ready_callback
        self.callback_msg_empty = msg_empty_callback
        self.callback_msg_sendable = msg_sendable_callback

        self.bufsize = bufsize

        self._last_recv_ts = time()
        executor.send_mainboard("X17O\n")

    @property
    def ready(self):
        return self._ready

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

    def _process_init(self, msg, executor):
        if self._ln is not None:
            if msg == "ok":
                self._ready = True
                if self.callback_ready:
                    self.callback_ready(self)
                    self.callback_ready = None
            else:
                L.deubg("Unhandle MB MSG: %s" % msg)
        else:
            if msg == "CTRL LINECHECK_ENABLED":
                self._ln = 0
                self._ln_ack = 0

            elif msg.startswith("ER MISSING_LINENUMBER "):
                L.error("Mainboard linecheck already enabled")
                # Try re-enbale line check
                ln = int(msg.split(" ")[2])
                self._send_cmd(executor, ln, "X17F")
                executor.send_mainboard("X17O\n")
            else:
                L.debug("Unhandle MB MSG: %s" % msg)

    def on_message(self, msg, executor):
        if self._ready:
            if msg.startswith("LN "):
                recv_ln, cmd_in_queue = (int(x) for x in msg.split(" ", 2)[1:])
                self._ln_ack = recv_ln
                self._last_recv_ts = time()
                self._resend_counter = 0

                this_cmd = self._cmd_sent.popleft()
                while this_cmd[0] < recv_ln:
                    self._cmd_padding.append(this_cmd)
                    L.info("Missing LN: %i" % this_cmd[0])
                    this_cmd = self._cmd_sent.popleft()

                while len(self._cmd_padding) > cmd_in_queue:
                    self._cmd_padding.popleft()
                self._cmd_padding.append(this_cmd)

            elif msg == "ok":
                self._cmd_padding.popleft()

                if self.buffered_cmd_size + 1 == self.bufsize and \
                   self.callback_msg_sendable:
                    self.callback_msg_sendable(self)
                if self.buffered_cmd_size == 0 and self.callback_msg_empty:
                    self.callback_msg_empty(self)

            elif msg.startswith("ER LINE_MISMATCH "):
                correct_ln = int(msg.split(" ")[2])
                if not self._resend_cmd_from(correct_ln, executor,
                                             ttl_offset=-2):
                    raise SystemError(EXEC_INTERNAL_ERROR,
                                      "IMPOSSIBLE_SYNC_LN")

            elif msg.startswith("ER CHECKSUM_MISMATCH "):
                err_ln = int(msg.split(" ")[2])
                if not self._resend_cmd_from(err_ln, executor,
                                             ttl_offset=-1):
                    raise SystemError(EXEC_INTERNAL_ERROR,
                                      "IMPOSSIBLE_SYNC_LN")

            else:
                L.info("Unhandle MB MSG: %s" % msg)
        else:
            self._process_init(msg, executor)


    def create_cmd(self, lineno, cmd):
        l = "%s N%i" % (cmd, lineno)
        s = 0
        for c in l:
            s ^= ord(c)
        return "%s*%i\n" % (l, s)

    def _resend_cmd_from(self, lineno, executor, ttl_offset):
        if lineno < self._ln_ack:
            return True

        if self._inhibit_resend:
            ttl, ts, i_ln = self._inhibit_resend
            if i_ln == lineno and time() - ts < 0.3 and ttl > 0:
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
                    self._send_cmd(executor, *cmdline)
                    ttl += 1

                if ttl > 0:
                    self._inhibit_resend = (ttl, time(), lineno)

                return True
            else:
                return False
        return False

    def send_cmd(self, cmd, executor):
        if self.ready and self.buffered_cmd_size < self._bufsize:
            self._ln += 1
            self._send_cmd(executor, self._ln, cmd)
            if not self._cmd_sent:
                self._last_recv_ts = time()
            self._cmd_sent.append((self._ln, cmd))
        else:
            raise RuntimeError(EXEC_OPERATION_ERROR, "BUF_FULL")

    def _send_cmd(self, executor, lineno, cmd):
        executor.send_mainboard(self.create_cmd(lineno, cmd))

    def reset_mainboard(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        L.error("Mainboard no response, restart it")
        try:
            s.connect(uart_config["control"])
            s.send(b"reset mb")
            s.close()
        except Exception:
            L.exception("Error while send resset mb signal")

    def patrol(self, executor):
        if not self._ready:
            if self._resend_counter >= 3:
                L.error("Mainboard no response, restart it")
                self.reset_mainboard()
                raise SystemError(EXEC_MAINBOARD_OFFLINE)

            if time() - self._last_recv_ts > 1.0:
                self._resend_counter += 1
                self._last_recv_ts = time()
                # Resend, let ttl_offset takes no effect
                executor.send_mainboard("X17O\n")

        if self._cmd_sent:
            if self._resend_counter >= 3:
                self._ready = False
                L.error("Mainboard no response, restart it")
                self.reset_mainboard()
                raise SystemError(EXEC_MAINBOARD_OFFLINE)

            if time() - self._last_recv_ts > 1.0:
                self._resend_counter += 1
                # Resend, let ttl_offset takes no effect
                self._resend_cmd_from(self._ln_ack + 1, executor,
                                      ttl_offset=-128)
