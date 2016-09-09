# from time import time

from fluxmonitor.player.head_controller import HeadController, HeadTypeError
from tests.player.misc import ControlTestBase, UnittestError


HELLO_MSG = ("1 OK HELLO TYPE:USER/EXTRUDER ID:1572870 VENDOR:FLUX\ .inc "
             "FIRMWARE:OHMAMA VERSION:1.0922 EXTRUDER:1 "
             "MAX_TEMPERATURE:235.0 *107")
WRONG_HELLO_MSG = ("1 OK HELLO TYPE:EXTRUDER ID:1572870 VENDOR:FLUX\ .inc "
                   "FIRMWARE:OHMAMA VERSION:1.0922 EXTRUDER:1 "
                   "MAX_TEMPERATURE:235.0 *85")
PING_CMD = "1 PING *33\n"
PONG_MSG = "1 OK PONG ER:0 RT:40.0 TT:0 FA:0 *63"

SEND_CMD = "WAWAWASUREMONO"
SEND_CMD_PAYLOAD = "1 WAWAWASUREMONO *53\n"
RESP_CMD = "OK WASUREMONO "
RESP_CMD_PAYLOAD = "1 OK WASUREMONO *17"

# ER_PONG_MSG = "1 OK PONG ER:8 RT:169.9 TT:170.0 FA:0 *28"
# HEAT_0_200_CMD = "1 H:0 T:200.0 *17\n"


class UserHeadControlTest(ControlTestBase):
    def setUp(self):
        super(UserHeadControlTest, self).setUp()

        with self.assertSendHeadboard('1 HELLO *115\n') as executor:
            hc = HeadController(executor, required_module="USER",
                                ready_callback=self.raiseException)
            hc.bootstrap(executor)
        self.head_ctrl = hc

    def tearDown(self):
        self.head_ctrl = None

    def test_hello(self):
        with self.assertSendHeadboard(PING_CMD) as executor:
            self.head_ctrl.on_message(HELLO_MSG, executor)
            self.assertRaises(UnittestError, self.head_ctrl.on_message,
                              PONG_MSG, executor)
        self.assertTrue(self.head_ctrl.ready)

    def test_wrong_head(self):
        with self.assertSendHeadboard() as executor:
            self.assertRaises(HeadTypeError, self.head_ctrl.on_message,
                              WRONG_HELLO_MSG, executor)

    def test_cmd(self):
        self.test_hello()
        with self.assertSendHeadboard(SEND_CMD_PAYLOAD) as executor:
            self.head_ctrl.send_cmd(SEND_CMD, executor)
            self.assertTrue(self.head_ctrl.is_busy)
            msg = self.head_ctrl.on_message(RESP_CMD_PAYLOAD, executor)
            self.assertEqual(msg, RESP_CMD)
        self.assertFalse(self.head_ctrl.is_busy)
