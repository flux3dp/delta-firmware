
from unittest import TestCase
import socket

from fluxmonitor.player.main_controller import MainController
# from fluxmonitor.config import uart_config
# from .misc import ControlTestBase, UnittestError

MAX_CMD_BUFSIZE = 16
FLAG_READY = 1


class MainboardControlTest(TestCase):
    callback_log = None

    def setUp(self):
        def msg_empty_callback(ctrl):
            self.callback_log.append(("empty", ctrl))

        def msg_sendable_callback(ctrl):
            self.callback_log.append(("sendable", ctrl))

        self.callback_log = []
        self.lsock, self.rsock = socket.socketpair()
        self.lsock.setblocking(False)
        self.rsock.setblocking(False)

        self.t = MainController(self.rsock.fileno(), MAX_CMD_BUFSIZE,
                                msg_empty_callback=msg_empty_callback,
                                msg_sendable_callback=msg_sendable_callback)

    def assertRecv(self, msg):  # noqa
        buf = self.lsock.recv(4096)
        self.assertEqual(buf, msg)

    def assertRecvStartsWith(self, msg):  # noqa
        buf = self.lsock.recv(4096)
        self.assertEqual(buf[:len(msg)], msg)

    def send_and_process(self, buf):
        self.lsock.send(buf)
        self.t.handle_recv()

    def test_bootstrap_simple(self):
        def callback(ctrl):
            self.callback_log.append((callback, ctrl))

        self.assertFalse(self.t.ready)
        self.t.bootstrap(callback)
        self.assertRecv(b"C1O\n")
        self.assertFalse(self.t.ready)
        self.send_and_process("CTRL LINECHECK_ENABLED\n")
        self.assertTrue(self.t.ready)
        self.assertEqual(self.callback_log, [(callback, self.t)])

    def test_bootstrap_no_response(self):
        def callback(ctrl):
            self.callback_log.append((callback, ctrl))

        self.assertFalse(self.t.ready)
        self.t.bootstrap(callback)
        self.assertRecv(b"C1O\n")

        for i in range(3):
            self.t.send_timestamp = 0
            self.t.patrol()
            self.assertRecv(b"C1O\n")

        self.t.send_timestamp = 0
        self.assertRaises(SystemError, self.t.patrol)
        self.assertEqual(self.callback_log, [])

    def test_bootstrap_with_lineno_enabled(self):
        def callback(ctrl):
            self.callback_log.append((callback, ctrl))

        self.assertFalse(self.t.ready)
        self.t.bootstrap(callback)
        self.assertRecv(b"C1O\n")
        self.send_and_process(b"ER MISSING_LINENUMBER 3\n")
        self.assertRecv(b"@DISABLE_LINECHECK\n")
        self.send_and_process(b"CTRL LINECHECK_DISABLED\n")
        self.assertRecv(b"C1O\n")
        self.send_and_process("CTRL LINECHECK_ENABLED\n")
        self.assertTrue(self.t.ready)
        self.assertEqual(self.callback_log, [(callback, self.t)])

    def _bootstrap(self):
        self.t.bootstrap(None)
        self.assertRecv(b"C1O\n")
        self.send_and_process("CTRL LINECHECK_ENABLED\n")

    def test_command_full_empty_callback(self):
        self._bootstrap()

        self.t.send_cmd(b"G28")
        self.assertRecv(b"G28 N1*18\n")

        self.assertEqual(self.t.buffered_cmd_size, 1)
        self.assertEqual(self.callback_log, [])

        self.send_and_process("LN 1 1\n")
        self.assertEqual(self.t.buffered_cmd_size, 1)
        self.assertEqual(self.callback_log, [])

        self.send_and_process("LN 1 0\n")
        self.assertEqual(self.t.buffered_cmd_size, 0)
        self.assertEqual(self.callback_log, [("empty", self.t)])
        self.callback_log = []

        self.t.send_cmd(b"G28")
        self.assertRecv(b"G28 N2*17\n")
        self.send_and_process("LN 2 0\n")
        self.assertEqual(self.callback_log, [("empty", self.t)])
        self.callback_log = []

        for i in range(MAX_CMD_BUFSIZE):
            self.t.send_cmd("G1 Z%i" % i)
            self.assertRecvStartsWith("G1 Z%i N%i" % (i, i + 3))

        self.send_and_process("LN 18 16\n")
        self.assertEqual(self.t.buffered_cmd_size, 16)

        self.callback_log = []
        self.send_and_process("LN 18 15\n")
        self.assertEqual(self.t.buffered_cmd_size, 15)
        self.assertEqual(self.callback_log, [("sendable", self.t)])

        self.callback_log = []
        self.send_and_process("LN 18 5\n")
        self.assertEqual(self.t.buffered_cmd_size, 5)
        self.send_and_process("LN 18 0\n")
        self.assertEqual(self.callback_log, [("empty", self.t)])
        self.assertEqual(self.t.buffered_cmd_size, 0)

    def test_send_command_workround(self):
        self._bootstrap()
        self.t._ln = 123

        for i in range(MAX_CMD_BUFSIZE):
            self.t.send_cmd("G1 Z%i" % i)
            self.assertRecvStartsWith("G1 Z%i N%i" % (i, i + 124))

        self.assertEqual(self.t.buffered_cmd_size, 16)
        self.send_and_process("LN 128 1\n")
        self.assertEqual(self.t.buffered_cmd_size, 12)

        self.t.send_cmd("G1 Z200")
        self.assertRecvStartsWith("G1 Z200 N140")
        self.assertEqual(self.t.buffered_cmd_size, 13)
        self.send_and_process("LN 138 11\n")
        self.assertEqual(self.t.buffered_cmd_size, 13)
        self.send_and_process("LN 140 1\n")
        self.assertEqual(self.t.buffered_cmd_size, 1)

    def test_msg_full(self):
        self._bootstrap()
        self.t._ln = 256
        for i in range(MAX_CMD_BUFSIZE):
            self.t.send_cmd("G1 Z%i" % i)
            self.assertRecvStartsWith("G1 Z%i N%i" % (i, i + 257))

        self.assertRaises(RuntimeError, self.t.send_cmd, "G28")

    def test_filament_runout(self):
        self._bootstrap()
        self.assertRaises(RuntimeError, self.send_and_process,
                          "CTRL FILAMENTRUNOUT 1\n")
        self.send_and_process("CTRL FILAMENTRUNOUT 1\n")
        self.send_and_process("CTRL FILAMENTRUNOUT 1\n")

        self.t.bootstrap()
        self.assertRaises(RuntimeError, self.send_and_process,
                          "CTRL FILAMENTRUNOUT 1\n")
        self.send_and_process("CTRL FILAMENTRUNOUT 1\n")

    def test_checksum_mismatch(self):
        self._bootstrap()
        self.t._ln = 512

        self.t.send_cmd("G1 Z210")
        self.assertRecv("G1 Z210 N513*102\n")
        self.send_and_process("ER CHECKSUM_MISMATCH 513\n")
        self.assertRecv("G1 Z210 N513*102\n")

    def test_checksum_mismatch_multi(self):
        self._bootstrap()
        self.t._ln = 515

        self.t.send_cmd("G1 Z210")
        self.assertRecvStartsWith("G1 Z210 N516")
        self.t.send_cmd("G1 Z215")
        self.assertRecvStartsWith("G1 Z215 N517")
        self.t.send_cmd("G1 Z205")
        self.assertRecvStartsWith("G1 Z205 N518")

        self.send_and_process("ER CHECKSUM_MISMATCH 516\n")
        self.assertRecv(
            "G1 Z210 N516*99\nG1 Z215 N517*103\nG1 Z205 N518*105\n")
        self.send_and_process("LN 516 517\n")
        self.send_and_process("LN 516 518\n")
        self.assertRaises(socket.error, self.lsock.recv, 4096)

    def test_ln_mismatch_multi(self):
        self._bootstrap()
        self.t._ln = 601

        self.t.send_cmd("G1 X5")
        self.assertRecvStartsWith("G1 X5 N602")
        self.t.send_cmd("G1 X6")
        self.assertRecvStartsWith("G1 X6 N603")
        self.t.send_cmd("G1 X7")
        self.assertRecvStartsWith("G1 X7 N604")
        self.t.send_cmd("G1 X8")
        self.assertRecvStartsWith("G1 X8 N605")

        self.send_and_process("LN 602 0\n")
        self.send_and_process("ER LINE_MISMATCH 603 604\n")
        self.assertRecv(
            "G1 X6 N603*99\nG1 X7 N604*101\nG1 X8 N605*107\n")
        self.send_and_process("ER LINE_MISMATCH 603 605\n")
        self.assertRaises(socket.error, self.lsock.recv, 4096)

    def test_resp_timeout(self):
        self._bootstrap()
        self.t._ln = 610
        self.t.send_cmd("G1 X8")
        self.assertRecvStartsWith("G1 X8 N611")

        for i in range(3):
            self.t.send_timestamp = 0
            self.t.patrol()
            self.assertRecvStartsWith("G1 X8 N611")

        self.t.send_timestamp = 0
        self.assertRaises(SystemError, self.t.patrol)
