
from time import time
import socket
import os

from fluxmonitor.code_executor.main_controller import MainController
from fluxmonitor.config import uart_config
from .misc import ControlTestBase


class MainboardControlStartupTest(ControlTestBase):
    def test_startup_simple(self):
        with self.assertSendMainboard(b"X17O\n") as executor:
            mc = MainController(executor, ready_callback=self.raiseException)

        with self.assertSendMainboard() as executor:
            mc.on_message("CTRL LINECHECK_ENABLED", executor)
        with self.assertSendMainboard() as executor:
            self.assertRaises(RuntimeWarning, mc.on_message, "ok", executor)
        self.assertTrue(mc.ready, True)

    def test_startup_no_response(self):
        with self.assertSendMainboard(b"X17O\n") as executor:
            mc = MainController(executor, ready_callback=self.raiseException)

        with self.assertSendMainboard() as executor:
            mc.patrol(executor)
        mc._last_recv_ts = -1
        with self.assertSendMainboard(b"X17O\n") as executor:
            # TTL: 1
            mc.patrol(executor)
        with self.assertSendMainboard() as executor:
            mc.patrol(executor)
        mc._last_recv_ts = -1
        with self.assertSendMainboard(b"X17O\n") as executor:
            # TTL: 2
            mc.patrol(executor)
        mc._last_recv_ts = -1
        with self.assertSendMainboard(b"X17O\n") as executor:
            # TTL: 3
            mc.patrol(executor)
        mc._last_recv_ts = -1
        with self.assertSendMainboard() as executor:
            # Bomb
            self.assertRaises(SystemError, mc.patrol, executor)

    def test_startup_with_lineno_enabled(self):
        with self.assertSendMainboard(b"X17O\n") as executor:
            mc = MainController(executor, ready_callback=self.raiseException)

        with self.assertSendMainboard(b"X17F N3*69\n", b"X17O\n") as executor:
            mc.on_message("ER MISSING_LINENUMBER 3", executor)

class MainboardControlTest(ControlTestBase):
    def setUp(self):
        super(MainboardControlTest, self).setUp()

        with self.assertSendMainboard(b"X17O\n") as executor:
            mc = MainController(executor, ready_callback=self.raiseException)

        mc._ln = 0
        mc._waitting_ok = False
        mc._ready = True
        mc.callback_ready = None
        self.mc = mc

    def preset(self, cmd_sent=None, cmd_padding=None, ln=0, ln_ack=0,
               last_recv_ln=None, resend_counter=0, msg_empty_callback=None,
               msg_sendable_callback=None):
        if cmd_padding:
            for cmdline in cmd_padding:
                self.mc._cmd_padding.append(cmdline)
        if cmd_sent:
            for cmdline in cmd_sent:
                self.mc._cmd_sent.append(cmdline)

        self.mc._ln = ln
        self.mc._ln_ack = ln_ack
        self.mc._last_recv_ts = last_recv_ln if last_recv_ln else time()
        self.mc._resend_counter = resend_counter

        if msg_empty_callback:
            self.mc.callback_msg_empty = msg_empty_callback
        if msg_sendable_callback:
            self.mc.callback_msg_sendable = msg_sendable_callback

    def test_append_command_from_empty(self):
        with self.assertSendMainboard(b"G28 N1*18\n") as executor:
            self.mc.send_cmd(b"G28", executor)

        self.assertItemsEqual(self.mc._cmd_sent,
                              ((1, b"G28"),))
        self.assertItemsEqual(self.mc._cmd_padding, ())
        self.assertEqual(self.mc._ln, 1)

    def test_append_command_from_not_empty(self):
        self.preset(cmd_sent=((1, b"G28"), ), ln=1)

        with self.assertSendMainboard(b"G1 Z0 N2*96\n") as executor:
            self.mc.send_cmd(b"G1 Z0", executor)
        self.assertItemsEqual(self.mc._cmd_sent, ((1, b"G28"), (2, b"G1 Z0")))
        self.assertItemsEqual(self.mc._cmd_padding, ())
        self.assertEqual(self.mc._ln, 2)

    def test_append_command_when_full(self):
        self.preset(cmd_padding=((1, "G"), (2, "G"), (3, "G"), (4, "G"),
                                 (5, "G"), (6, "G"), (7, "G")),
                    cmd_sent=((8, "G"), (9, "G"), (10, "G"), (11, "G"),
                              (12, "G"), (13, "G"), (14, "G"), (15, "G"),
                              (16, "G")),
                    ln=16, ln_ack=7)

        self.assertRaises(RuntimeError, self.mc.send_cmd, b"G1 Z0", self)

    def test_recv_ln_normal(self):
        self.preset(cmd_sent=((1, b"G28 N1*18\n"), (2, b"G1 Z0 N2*96\n"),
                              (3, b"G1 X5 N3*102\n")),
                    ln=3)

        self.mc.on_message("LN 1 0", self)
        self.assertItemsEqual(self.mc._cmd_sent,
                              ((2, b"G1 Z0 N2*96\n"), (3, b"G1 X5 N3*102\n")))
        self.assertItemsEqual(self.mc._cmd_padding, ((1, b"G28 N1*18\n"), ))

        self.mc.on_message("LN 2 1", self)
        self.assertItemsEqual(self.mc._cmd_sent, ((3, b"G1 X5 N3*102\n"), ))
        self.assertItemsEqual(self.mc._cmd_padding,
                              ((1, b"G28 N1*18\n"), (2, b"G1 Z0 N2*96\n")))

    def test_recv_ln_skiped(self):
        self.preset(cmd_sent=((1, b"G28 N1*18\n"), (2, b"G1 Z0 N2*96\n"),
                              (3, b"G1 X5 N3*102\n")),
                    ln=3)

        self.mc.on_message("LN 2 1", self)
        self.assertItemsEqual(self.mc._cmd_sent, ((3, b"G1 X5 N3*102\n"), ))
        self.assertItemsEqual(self.mc._cmd_padding,
                              ((1, b"G28 N1*18\n"), (2, b"G1 Z0 N2*96\n")))

    def test_missing_the_second_last_msg(self):
        self.preset(cmd_sent=((1, b"G28"), (2, b"G1 Z0"), (3, b"G1 X5")),
                    ln=3)

        with self.assertSendMainboard(b"G1 Z0 N2*96\n",
                                      b"G1 X5 N3*102\n") as executor:
            self.mc.on_message("ER LINE_MISMATCH 2 3", executor)

    def test_missing_the_third_last_msg(self):
        self.preset(cmd_sent=((1, b"G28"), (2, b"G1 Z0"), (3, b"G1 X5"),
                              (4, b"G1 Y5")),
                    ln=3)

        with self.assertSendMainboard(b"G1 Z0 N2*96\n", b"G1 X5 N3*102\n",
                                      b"G1 Y5 N4*96\n") as executor:
        # This ER message trigger by command N3
            self.mc.on_message("ER LINE_MISMATCH 2 3", executor)

        # This ER message trigger by command N4 and controller will not try
        # to resend because ER message comes too close
        with self.assertSendMainboard() as executor:
            self.mc.on_message("ER LINE_MISMATCH 2 3", executor)

    def test_checksumerr_the_second_last_msg(self):
        self.preset(cmd_sent=((1, b"G28"), (2, b"G1 Z0"), (3, b"G1 X5")),
                    ln=3)

        # This ER message trigger by command N2 self
        with self.assertSendMainboard(b"G1 Z0 N2*96\n",
                                      b"G1 X5 N3*102\n") as executor:
            self.mc.on_message("ER CHECKSUM_MISMATCH 2", executor)

        # This ER message trigger by command N3 because N2 got checksum error,
        # and is fixed before. This ER message comes too close, ignore
        with self.assertSendMainboard() as executor:
            self.mc.on_message("ER LINE_MISMATCH 2 3", executor)

    def test_timeout_and_resend(self):
        self.preset(cmd_sent=((1, b"G28"), (2, b"G1 Z0"), (3, b"G1 X5")),
                    ln=3, last_recv_ln=time() - 10)

        with self.assertSendMainboard(b"G28 N1*18\n", b"G1 Z0 N2*96\n",
                                      b"G1 X5 N3*102\n") as executor:
            self.mc.patrol(executor)

    def test_mainboard_no_response(self):
        if os.path.exists(uart_config["control"]):
            os.unlink(uart_config["control"])

        uart_ctrl = socket.socket(socket.AF_UNIX)
        uart_ctrl.setblocking(False)
        uart_ctrl.bind(uart_config["control"])
        uart_ctrl.listen(1)

        self.preset(cmd_sent=((1, b"G28 N1*18\n"), (2, b"G1 Z0 N2*96\n"),
                              (3, b"G1 X5 N3*102\n")),
                    ln=3, last_recv_ln=time() - 10, resend_counter=4)

        self.assertRaises(SystemError, self.mc.patrol, self)

        # Check if reset send
        self.assertEqual(uart_ctrl.accept()[0].recv(4096), b"reset mb")

        self.assertFalse(self.mc.ready)

        with self.assertSendMainboard() as executor:
            self.assertRaises(RuntimeError, self.mc.send_cmd, b"G1 X0",
                              executor)

    def test_msg_empty_callback(self):
        self.preset(cmd_padding=((1, b"G28 N1*18\n"), (2, b"G1 Z0 N2*96\n")),
                    ln=2, ln_ack=2, msg_empty_callback=self.raiseException)

        with self.assertSendMainboard() as executor:
            self.mc.on_message("ok", executor)
        self.assertItemsEqual(self.mc._cmd_padding, ((2, b"G1 Z0 N2*96\n"), ))

        with self.assertSendMainboard() as executor:
            self.assertRaises(RuntimeWarning, self.mc.on_message, "ok",
                              executor)
        self.assertItemsEqual(self.mc._cmd_padding, ())

    def test_msg_sendable_callback(self):
        self.preset(cmd_padding=((1, "G"), (2, "G"), (3, "G"), (4, "G"),
                                 (5, "G"), (6, "G"), (7, "G")),
                    cmd_sent=((8, "G"), (9, "G"), (10, "G"), (11, "G"),
                              (12, "G"), (13, "G"), (14, "G"), (15, "G"),
                              (16, "G")),
                    ln=16, ln_ack=7, msg_sendable_callback=self.raiseException)

        with self.assertSendMainboard() as executor:
            self.assertRaises(RuntimeWarning, self.mc.on_message, "ok",
                              executor)
