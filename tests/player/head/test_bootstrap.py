
from fluxmonitor.player.head_controller import HeadController
from tests.player.misc import ControlTestBase, UnittestError


HELLO_MSG = {
    "EXTRUDER": ("1 OK HELLO TYPE:EXTRUDER ID:1572870 VENDOR:FLUX\ .inc "
                 "FIRMWARE:OHMAMA VERSION:1.0922 EXTRUDER:1 "
                 "MAX_TEMPERATURE:235.0 *85"),
    "LASER": ("1 OK HELLO TYPE:LASER ID:3f1f2a VENDOR:flux\ .inc "
              "FIRMWARE:xxxxxx VERSION:0.1.9 FOCAL_LENGTH:3.1 *52")
}
PING_CMD = "1 PING *33\n"
PONG_MSG = "1 OK PONG ER:0 RT:40.0 TT:0 FA:0 *63"
ER8_PONG_MSG = "1 OK PONG ER:8 RT:40.0 TT:0 FA:0 *55"


class StartUpTest(ControlTestBase):
    def test_send_hello(self):
        with self.assertSendHeadboard(b"1 HELLO *115\n") as executor:
            ec = HeadController(executor, required_module="EXTRUDER",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)

    def test_send_bad_message(self):
        with self.assertSendHeadboard(b"1 HELLO *115\n") as executor:
            ec = HeadController(executor, required_module="EXTRUDER",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)
        with self.assertSendHeadboard() as executor:
            ec.on_message("NOBODY", executor)

    def test_extruder(self):
        with self.get_executor() as executor:
            ec = HeadController(executor, required_module="EXTRUDER",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)

        with self.assertSendHeadboard(b"1 PING *33\n") as executor:
            ec.on_message(HELLO_MSG["EXTRUDER"], executor)

        with self.assertSendHeadboard(b"1 F:0 S:0 *4\n") as executor:
            ec.on_message(PONG_MSG, executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(UnittestError, ec.on_message, "1 OK FAN *92",
                              executor)
        self.assertTrue(ec.ready)

    def test_laser(self):
        with self.get_executor() as executor:
            ec = HeadController(executor, required_module="LASER",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)
        with self.assertSendHeadboard(PING_CMD) as executor:
            ec.on_message(HELLO_MSG["LASER"], executor)
            self.assertRaises(UnittestError, ec.on_message, PONG_MSG,
                              executor)
        self.assertTrue(ec.ready)

    def test_wrong_head(self):
        with self.get_executor() as executor:
            ec = HeadController(executor, required_module="EXTRUDER",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError, ec.on_message, HELLO_MSG["LASER"],
                              executor)

    def test_none_head(self):
        with self.get_executor() as executor:
            ec = HeadController(executor, required_module=None,
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)
        with self.assertSendHeadboard() as executor:
            ec._cmd_sent_at = 0
            self.assertRaises(UnittestError, ec.patrol, executor)
        self.assertTrue(ec.ready)

    def test_na_head(self):
        with self.get_executor() as executor:
            ec = HeadController(executor, required_module="N/A",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)
        with self.assertSendHeadboard() as executor:
            ec._cmd_sent_at = 0
            self.assertRaises(UnittestError, ec.patrol, executor)
        self.assertTrue(ec.ready)

    def test_ping_error_after_hello(self):
        with self.get_executor() as executor:
            ec = HeadController(executor, required_module="EXTRUDER",
                                ready_callback=self.raiseException)
            ec.bootstrap(executor)

        with self.assertSendHeadboard(PING_CMD) as executor:
            ec.on_message(HELLO_MSG["EXTRUDER"], executor)

        with self.assertSendHeadboard(PING_CMD) as executor:
            ec.on_message(ER8_PONG_MSG, executor)

        with self.assertSendHeadboard() as executor:
            ec._timer = 0
            self.assertRaises(RuntimeError, ec.on_message, ER8_PONG_MSG,
                              executor)
