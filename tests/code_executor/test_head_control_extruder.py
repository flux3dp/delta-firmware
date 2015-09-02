
from time import time

from fluxmonitor.code_executor.head_controller import ExtruderController
from .misc import ControlTestBase


R_MESSAGES = """*************************************************
FLUX Printer Module
FW_Version : v1.0

Current Temprature :2006
Temperature Limit :100
Kp :300
Ki :90
Kd :5000
Heater Status : ON
Setpoint :2005
t flag :0
Fan1 Status : ON
Fan2 Status : ON

s flag :0
k flag :0
sensor calibration :0
*************************************************"""


class ExtruderHeadControlTest(ControlTestBase):
    def setUp(self):
        super(ExtruderHeadControlTest, self).setUp()

        self.setHeadboardSendSequence("R\n")
        ec = ExtruderController(self, ready_callback=self.raiseException)

        self.assertSendHeadboardCalled()

        self.setHeadboardSendSequence("F10\n")
        for msg in R_MESSAGES.split("\n"):
            ec.on_message(msg, self)
        self.assertSendHeadboardCalled()

        self.assertRaises(RuntimeWarning, ec.on_message, "ok@F", self)
        self.assertSendHeadboardCalled()
        self.assertTrue(ec.ready)

        self.ec = ec

    def test_standard_operation(self):
        self.setHeadboardSendSequence("H2000\n")
        self.ec.set_heater(self, 0, 200, callback=self.raiseException)
        self.assertSendHeadboardCalled()
        self.assertRaises(RuntimeWarning, self.ec.on_message, "ok@H", self)

    def test_cmd_complete_callback(self):
        self.setHeadboardSendSequence(b"H2010\n")
        self.ec.set_heater(self, 0, 201, self.raiseException)

        self.ec.on_message("DARA", self)
        self.ec.on_message("DA~RA~", self)
        self.assertRaises(RuntimeWarning, self.ec.on_message, "ok@H2010", self)

    def test_wait_heaters(self):
        self.setHeadboardSendSequence(b"H2000\n")
        self.ec.set_heater(self, 0, 200)
        self.assertSendHeadboardCalled()

        self.ec.wait_heaters(self.raiseException)
        self.setHeadboardSendSequence(b"T\n")
        self.ec.patrol(self)

        self.assertRaises(RuntimeWarning, self.ec.on_message,
                          " abc: 123 >>> 2000", self)

    def test_cmd_timeout(self):
        self.ec._lastupdate = time()

        self.setHeadboardSendSequence(b"H2000\n")
        self.ec.set_heater(self, 0, 200)
        self.assertSendHeadboardCalled()

        # Error because command not ready
        self.assertRaises(RuntimeError, self.ec.set_heater, self, 0, 200)

        self.setHeadboardSendSequence(b"H2000\n", "H2000\n", "H2000\n")
        for i in range(1, 4):
            self.ec._cmd_sent_at = -1
            self.ec.patrol(self)
            self.assertEqual(self.ec._cmd_retry, i)
        self.assertSendHeadboardCalled()

        self.ec._cmd_sent_at = -1
        self.assertRaises(RuntimeError, self.ec.patrol, self)

    def test_update_timeout(self):
        self.setHeadboardSendSequence(b"T\n", b"T\n", b"T\n", b"T\n")

        for i in range(4):
            # 1(first) + 3(retry) = call 4 times
            self.ec._lastupdate = -1
            self.ec.patrol(self)
            self.assertEqual(self.ec._update_retry, i)
        self.assertSendHeadboardCalled()

        self.ec._lastupdate = -1
        self.assertRaises(RuntimeError, self.ec.patrol, self)

    def test_rebootstrap(self):
        self.assertTrue(self.ec.ready)
        self.assertRaises(RuntimeError, self.ec.on_message, "Boot", self)
        self.assertFalse(self.ec.ready)

        self.setHeadboardSendSequence("R\n")
        self.ec.bootstrap(self)
        self.assertSendHeadboardCalled()

        self.setHeadboardSendSequence("F10\n")
        for msg in R_MESSAGES.split("\n"):
            self.ec.on_message(msg, self)

        self.assertSendHeadboardCalled()

        self.assertRaises(RuntimeWarning, self.ec.on_message, "ok@F", self)
        self.assertSendHeadboardCalled()
