
from .sharedlib import SharedTestCase

from fluxmonitor.player.head_controller import HeadController
# from tests.player.misc import ControlTestBase, UnittestError

EXTRUDER_HELLO_MSG = ("1 OK HELLO TYPE:EXTRUDER ID:1572870 VENDOR:FLUX\ .inc "
                      "FIRMWARE:OHMAMA VERSION:1.0922 EXTRUDER:1 "
                      "MAX_TEMPERATURE:235.0 *85")
PING_CMD = "1 PING *33\n"
PONG_MSG = "1 OK PONG ER:0 RT:40.0 TT:0 FA:0 *63\n"
PONG_MSG_ER4 = "1 OK PONG ER:4 RT:40.0 TT:0 FA:0 *59\n"


class DurarararaControlTest(SharedTestCase):
    def setUp(self):
        SharedTestCase.setUp(self)
        self.t = HeadController(self.rsock.fileno())

    def test_durararara(self):
        self.t.bootstrap()
        self.t.send_timestamp = 0
        self.assertFalse(self.t.ready)
        self.t.patrol()
        self.assertTrue(self.t.ready)

        self.assertRaises(RuntimeError, self.send_and_process, PONG_MSG_ER4)
        self.assertFalse(self.t.ready)

    # def setUp(self):
    #     super(DurarararaControlTest, self).setUp()

    #     with self.get_executor() as executor:
    #         ec = HeadController(executor, required_module=None,
    #                             ready_callback=self.raiseException)
    #         ec.bootstrap(executor)
    #     with self.get_executor() as executor:
    #         ec._cmd_sent_at = 0
    #         self.assertRaises(UnittestError, ec.patrol, executor)
    #     self.assertTrue(ec.ready)
    #     self.ec = ec

    # def test_ping_ping_ping(self):
    #     with self.assertSendHeadboard("1 PING *33\n", "1 PING *33\n",
    #                                   "1 PING *33\n", ) as executor:
    #         self.ec._lastupdate = 0
    #         self.ec.patrol(executor)
    #         self.ec._lastupdate = 0
    #         self.ec.patrol(executor)
    #         self.ec._lastupdate = 0
    #         self.ec.patrol(executor)

    # def test_ping_pong(self):
    #     with self.assertSendHeadboard("1 PING *33\n") as executor:
    #         self.ec._lastupdate = 0
    #         self.ec.patrol(executor)
    #         self.assertRaises(RuntimeError, self.ec.on_message,
    #                           "1 OK PONG ER:4 RT:40.0 TT:0 FA:0 *59", executor)

    # def test_reset_and_hello(self):
    #     with self.assertSendHeadboard("1 HELLO *115\n", "1 PING *33\n",
    #                                   "1 H:0 T:220.0 *19\n") as executor:
    #         self.assertTrue(self.ec.ready)
    #         self.assertRaises(RuntimeError, self.ec.on_message,
    #                           "1 OK PONG ER:4 RT:40.0 TT:0 FA:0 *59", executor)
    #         self.assertFalse(self.ec.ready)
    #         self.ec.bootstrap(executor)
    #         self.assertEqual(self.ec.module, "N/A")
    #         self.ec.on_message(EXTRUDER_HELLO_MSG, executor)
    #         self.assertRaises(UnittestError, self.ec.on_message,
    #                           PONG_MSG, executor)
    #         self.assertEqual(self.ec.module, "EXTRUDER")
    #         self.ec.send_cmd("H0220", executor)
    #         self.ec.on_message("1 OK HEATER *26",
    #                            executor)
    #         self.ec.on_message("1 OK PONG ER:0 RT:15.0 TT:220 FA:0 *63",
    #                            executor)
    #         st = self.ec.status()
    #         self.assertEqual(st["rt"], (15,))
    #         self.assertEqual(st["tt"], (220,))
    #         self.assertEqual(st["module"], "EXTRUDER")

    # def test_extruder_offline(self):
    #     with self.assertSendHeadboard(PING_CMD, "1 HELLO *115\n",
    #                                   PING_CMD, PING_CMD, PING_CMD, PING_CMD,
    #                                   PING_CMD, PING_CMD) as executor:
    #         self.ec.patrol(executor)
    #         self.assertRaises(RuntimeError, self.ec.on_message,
    #                           "1 OK PONG ER:4 RT:40.0 TT:0 FA:0 *59", executor)
    #         self.ec.bootstrap(executor)
    #         self.ec.on_message(EXTRUDER_HELLO_MSG, executor)
    #         self.assertRaises(UnittestError, self.ec.on_message,
    #                           PONG_MSG, executor)
    #         self.assertTrue(self.ec.ready)
    #         for i in range(5):
    #             self.ec._lastupdate = 0
    #             self.ec.patrol(executor)
    #         self.ec._lastupdate = 0
    #         self.assertRaises(RuntimeError, self.ec.patrol, executor)
