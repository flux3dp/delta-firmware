
from collections import deque
from time import time
import logging
import socket

from fluxmonitor.err_codes import EXEC_OPERATION_ERROR, EXEC_INTERNAL_ERROR,\
    EXEC_MAINBOARD_OFFLINE, EXEC_FILAMENT_RUNOUT


L = logging.getLogger(__name__)

FLAG_READY = 1
FLAG_CLOSED = 2


class MainController(object):
    # Number, from 0
    _ln = None  # current sequence
    _ln_ack = None  # Mainboard confirmd sequence

    # Communicate counter
    _last_recv_ts = -1  # Timestemp: last recive "LN x" message
    _resend_counter = 0  # Resend counter

    # Booean
    _flags = 0

    _retry_ttl = 3

    # Callable object
    _callback_ready = None
    # Tuple: (ttl(int), time(float), ln(int))
    _inhibit_resend = None

    _bufsize = None

    def __init__(self, executor, bufsize=16, ready_callback=None,
                 msg_empty_callback=None, msg_sendable_callback=None,
                 retry_ttl=3):
        self._retry_ttl = retry_ttl

        self._cmd_sent = deque()
        self._cmd_padding = deque()
        self.callback_ready = ready_callback
        self.callback_msg_empty = msg_empty_callback
        self.callback_msg_sendable = msg_sendable_callback

        self.bufsize = bufsize

        self._last_recv_ts = time()
        executor.send_mainboard("C1O\n")

    @property
    def ready(self):
        return (self._flags & FLAG_READY) > 0

    @property
    def closed(self):
        return (self._flags & FLAG_CLOSED) > 0

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
        if msg == "CTRL LINECHECK_ENABLED":
            self._ln = 0
            self._ln_ack = 0
            self._flags |= FLAG_READY
            if self.callback_ready:
                self.callback_ready(self)
                self.callback_ready = None

        elif msg.startswith("ER MISSING_LINENUMBER "):
            L.error("Mainboard linecheck already enabled")
            # Try re-enbale line check
            ln = int(msg.split(" ")[2])
            self._send_cmd(executor, ln, "C1F")
        elif msg == "CTRL LINECHECK_DISABLED":
            executor.send_mainboard("C1O\n")
        else:
            L.debug("Recv unknow msg: '%s'", msg)

    def remove_complete_command(self, cmd=None):
        self._cmd_padding.popleft()

        if self.buffered_cmd_size + 1 == self.bufsize and \
           self.callback_msg_sendable:
            self.callback_msg_sendable(self)
        if self.buffered_cmd_size == 0 and self.callback_msg_empty:
            self.callback_msg_empty(self)

    def on_message(self, msg, executor):
        if self._resend_counter > 0:
            L.error("@ %s" % msg)
        if self.ready:
            if msg.startswith("LN "):
                recv_ln, cmd_in_queue = (int(x) for x in msg.split(" ", 2)[1:])
                self._last_recv_ts = time()
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
                raise RuntimeError(EXEC_FILAMENT_RUNOUT, msg.split(" ")[2])

            elif msg == "CTRL LINECHECK_DISABLED":
                executor.send_mainboard(b"C1O\n")

            elif msg == "CTRL STASH":
                pass

            elif msg == "CTRL STASH_POP":
                pass

            elif msg == "ok":
                pass

            else:
                if msg.startswith("ER "):
                    raise SystemError(*(msg.split(" ")[1:]))

                L.debug("Unhandle MB MSG: %s" % msg)
        elif not self.closed:
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

    def send_cmd(self, cmd, executor, force=False):
        if self.ready:
            if self.buffered_cmd_size < self._bufsize or force:
                self._ln += 1
                self._send_cmd(executor, self._ln, cmd)
                if not self._cmd_sent:
                    self._last_recv_ts = time()
                self._cmd_sent.append((self._ln, cmd))
            else:
                raise RuntimeError(EXEC_OPERATION_ERROR, "BUF_FULL")
        else:
            raise RuntimeError(EXEC_OPERATION_ERROR, "NOT_READY")

    def _send_cmd(self, executor, lineno, cmd):
        executor.send_mainboard(self.create_cmd(lineno, cmd))

    def on_mainboard_dead(self):
        self._flags &= ~FLAG_READY
        self._flags |= FLAG_CLOSED
        raise SystemError(EXEC_MAINBOARD_OFFLINE)

    def close(self, executor):
        if self.ready:
            executor.send_mainboard("@DISABLE_LINECHECK\n")
            executor.send_mainboard("G28\n")
            self._flags &= ~FLAG_READY
            self._flags |= FLAG_CLOSED

    def patrol(self, executor):
        if not self.ready and not self.closed:
            if time() - self._last_recv_ts > 1.0:
                self._resend_counter += 1
                if self._resend_counter > self._retry_ttl:
                    L.error("Mainboard no response, restart it")
                    self.on_mainboard_dead()

                self._last_recv_ts = time()
                # Resend, let ttl_offset takes no effect
                executor.send_mainboard("C1O\n")

        if self._cmd_sent:
            if self._resend_counter >= self._retry_ttl:
                L.error("Mainboard no response, restart it (%i)",
                        self._resend_counter)
                self.on_mainboard_dead()

            if time() - self._last_recv_ts > 3.0:
                self._last_recv_ts = time()
                self._resend_counter += 1
                # Resend, let ttl_offset takes no effect
                self._resend_cmd_from(self._ln_ack + 1, executor,
                                      ttl_offset=-128)
