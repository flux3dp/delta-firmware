
from time import time

from fluxmonitor.player.head_controller import HeadController
from .misc import ControlTestBase, UnittestError


HELLO_MSG = ("1 OK HELLO TYPE:EXTRUDER ID:1572870 VENDOR:FLUX\ .inc "
              "FIRMWARE:OHMAMA VERSION:1.0922 EXTRUDER:1 "
              "MAX_TEMPERATURE:235.0 *85")


class ExtruderHeadControlTest(ControlTestBase):
    def setUp(self):
        super(ExtruderHeadControlTest, self).setUp()

        with self.assertSendHeadboard(b"1 HELLO *115\n") as executor:
            ec = HeadController(executor, required_module="EXTRUDER",
                                ready_callback=self.raiseException)

        with self.assertSendHeadboard(b"1 F:0 S:0 *4\n") as executor:
            ec.on_message(HELLO_MSG, executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(UnittestError, ec.on_message, "1 OK FAN *92",
                              executor)
        self.assertTrue(ec.ready)
        self.ec = ec

    def test_standard_operation(self):
        with self.assertSendHeadboard(b"1 H:0 T:200.0 *17\n") as executor:
            self.ec.send_cmd("H200", executor,
                             complete_callback=self.raiseException)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(UnittestError, self.ec.on_message,
                              "1 OK HEATER *26", executor)

    def test_cmd_complete_callback(self):
        with self.assertSendHeadboard(b"1 H:0 T:201.0 *16\n") as executor:
            self.ec.send_cmd("H201", executor,
                             complete_callback=self.raiseException)

        with self.assertSendHeadboard() as executor:
            self.ec.on_message("DARA", executor)
            self.ec.on_message("DA~RA~", executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(UnittestError, self.ec.on_message,
                              "1 OK HEATER *26", executor)

    def test_wait_heaters(self):
        with self.assertSendHeadboard(b"1 H:0 T:200.0 *17\n") as executor:
            self.ec.send_cmd("H200", executor)
            self.ec.on_message("1 OK HEATER *26", executor)

        self.ec.wait_allset(self.raiseException)

        with self.assertSendHeadboard(b"1 PING *33\n") as executor:
            self.ec.patrol(executor)

        with self.assertSendHeadboard() as executor:
            self.ec.on_message("1 OK PONG ER:0 RT:160 TT:200.0 FA:0 *18",
                               executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(UnittestError, self.ec.on_message,
                              "1 OK PONG ER:0 RT:199.4 TT:200.0 FA:0 *18",
                              executor)

    def test_cmd_timeout(self):
        self.ec._lastupdate = time()

        with self.assertSendHeadboard(b"1 H:0 T:200.0 *17\n") as executor:
            self.ec.send_cmd("H200", executor)

        # Error because command not ready
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError,
                              self.ec.send_cmd, "H200", executor)

        with self.assertSendHeadboard(b"1 H:0 T:200.0 *17\n",
                                      b"1 H:0 T:200.0 *17\n",
                                      b"1 H:0 T:200.0 *17\n") as executor:
            for i in range(1, 4):
                self.ec._cmd_sent_at = -1
                self.ec.patrol(executor)
                self.assertEqual(self.ec._cmd_retry, i)

        self.ec._cmd_sent_at = -1
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError, self.ec.patrol, executor)

    def test_update_timeout(self):
        for i in range(4):
            with self.assertSendHeadboard(b"1 PING *33\n") as executor:
                # 1(first) + 3(retry) = call 4 times
                self.ec._lastupdate = -1
                self.ec.patrol(executor)
                self.assertEqual(self.ec._update_retry, i)

        self.ec._lastupdate = -1
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError, self.ec.patrol, executor)

    def test_rebootstrap(self):
        self.assertTrue(self.ec.ready)
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError, self.ec.on_message,
                              b"1 OK PONG ER:4 RT:199.5 TT:200.0 FA:0 *23",
                              executor)
        self.assertFalse(self.ec.ready)

        with self.assertSendHeadboard(b"1 HELLO *115\n") as executor:
            self.ec.bootstrap(executor)

        with self.assertSendHeadboard(b"1 F:0 S:0 *4\n") as executor:
            self.ec.on_message(HELLO_MSG, executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(UnittestError, self.ec.on_message,
                              "1 OK FAN *92", executor)
