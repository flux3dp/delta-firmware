#
from fluxmonitor.player.macro import ZprobeMacro
from fluxmonitor.storage import Metadata

from tests.player.misc import ControlTestBase


class CorrectionMacroTest(ControlTestBase):
    @classmethod
    def setUpClass(cls):
        cls.meta = Metadata()

    @classmethod
    def tearDownClass(cls):
        cls.meta = None

    def on_success_callback(self):
        self.assertIsNone(self.callback_status)
        self.callback_status = "OK"

    def on_error_callback(self, err_code):
        self.assertIsNone(self.callback_status)
        self.callback_status = err_code

    def reset_callback(self):
        self.callback_status = None

    def setUp(self):
        self.reset_callback()
        self.meta.plate_correction = {"X": 0, "Y":0, "Z": 0, "H": 242}
        self.cm = ZprobeMacro(self.on_success_callback)

    def test_simple_run(self):
        ## ROUND 0
        with self.assertSendMainboard("G30X0Y0") as executor:
            self.cm.start(executor)
        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:0 Y:0 = 0.3", executor)
        self.assertEqual(self.cm.data, 0.3)

        with self.assertSendMainboard("M666H241.7000",
                                      "G30X0Y0") as executor:
            self.cm.on_command_empty(executor)
            self.assertEqual(self.meta.plate_correction["H"], 241.7)

        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:0 Y:0 = 0.01", executor)
        self.assertEqual(self.cm.data, 0.01)
        with self.assertSendMainboard("G28") as executor:
            self.assertIsNone(self.callback_status)
            self.cm.on_command_empty(executor)
            self.cm.on_command_empty(executor)
            self.assertEqual(self.callback_status, "OK")


    def test_failed_run(self):
        self.cm.ttl = 1
        with self.assertSendMainboard("G30X0Y0", "G30X0Y0") as executor:
            self.cm.start(executor)
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:-73.6122 Y:-42.5 = 100", executor)
            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:-73.6122 Y:-42.5 = 100", executor)

        # Calculate
        self.assertIsNone(self.callback_status)
        with self.assertSendMainboard("G28") as executor:
            self.cm.on_command_empty(executor)
            self.assertEqual(self.callback_status, "CONVERGENCE_FAILED")
