
from time import time

from fluxmonitor.code_executor.head_controller import ExtruderController
from .misc import ControlTestBase


R_MESSAGES = "FLUX Printer Module"


class ExtruderHeadControlTest(ControlTestBase):
    def setUp(self):
        super(ExtruderHeadControlTest, self).setUp()

        with self.assertSendHeadboard(b"RM\n") as executor:
            ec = ExtruderController(executor,
                                    ready_callback=self.raiseException)

        with self.assertSendHeadboard(b"F10\n") as executor:
            for msg in R_MESSAGES.split("\n"):
                ec.on_message(msg, executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeWarning, ec.on_message, "ok@F10",
                              executor)
        self.assertTrue(ec.ready)
        self.ec = ec

    def test_standard_operation(self):
        with self.assertSendHeadboard(b"H2000\n") as executor:
            self.ec.set_heater(executor, 0, 200, callback=self.raiseException)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeWarning, self.ec.on_message, "ok@H2000",
                              executor)

    def test_cmd_complete_callback(self):
        with self.assertSendHeadboard(b"H2010\n") as executor:
            self.ec.set_heater(executor, 0, 201, self.raiseException)

        with self.assertSendHeadboard() as executor:
            self.ec.on_message("DARA", executor)
            self.ec.on_message("DA~RA~", executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeWarning, self.ec.on_message, "ok@H2010",
                              executor)

    def test_wait_heaters(self):
        with self.assertSendHeadboard(b"H2000\n") as executor:
            self.ec.set_heater(executor, 0, 200)

        self.ec.wait_heaters(self.raiseException)

        with self.assertSendHeadboard(b"T\n") as executor:
            self.ec.patrol(executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeWarning, self.ec.on_message,
                              " adc: 123 >>> 2000", executor)

    def test_cmd_timeout(self):
        self.ec._lastupdate = time()

        with self.assertSendHeadboard(b"H2000\n") as executor:
            self.ec.set_heater(executor, 0, 200)

        # Error because command not ready
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError,
                              self.ec.set_heater, executor, 0, 200)

        with self.assertSendHeadboard(b"H2000\n", b"H2000\n",
                                      b"H2000\n") as executor:
            for i in range(1, 4):
                self.ec._cmd_sent_at = -1
                self.ec.patrol(executor)
                self.assertEqual(self.ec._cmd_retry, i)

        self.ec._cmd_sent_at = -1
        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeError, self.ec.patrol, executor)

    def test_update_timeout(self):
        with self.assertSendHeadboard(b"T\n", b"T\n", b"T\n",
                                      b"T\n") as executor:
            for i in range(4):
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
            self.assertRaises(RuntimeError,
                              self.ec.on_message, b"Boot", executor)
        self.assertFalse(self.ec.ready)

        with self.assertSendHeadboard(b"RM\n") as executor:
            self.ec.bootstrap(executor)

        with self.assertSendHeadboard(b"F10\n") as executor:
            for msg in R_MESSAGES.split("\n"):
                self.ec.on_message(msg, executor)

        with self.assertSendHeadboard() as executor:
            self.assertRaises(RuntimeWarning,
                              self.ec.on_message, "ok@F10", executor)
