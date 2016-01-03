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
        self.meta.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 242}
        self.cm = ZprobeMacro(self.on_success_callback)

    def test_simple_run(self):
        # ROUND 0
        with self.assertSendMainboard("M666H242", "G30X0Y0") as executor:
            self.cm.start(executor)
            self.cm.on_command_empty(executor)

        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:0 Y:0 = 0.3", executor)
        self.assertEqual(self.cm.data, 0.3)

        # ROUND 1
        with self.assertSendMainboard("M666H241.7000", "G30X0Y0") as executor:
            self.cm.on_command_empty(executor)
            self.assertEqual(self.meta.plate_correction["H"], 241.7)

        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:0 Y:0 = 0.01", executor)
        self.assertEqual(self.cm.data, 0.01)

        # Complete
        with self.assertSendMainboard("M666H241.6900",
                                      "G1F6000Z50") as executor:
            self.assertIsNone(self.callback_status)
            self.cm.on_command_empty(executor)
            self.cm.on_command_empty(executor)
            self.assertEqual(self.callback_status, "OK")

    def test_failed_run(self):
        self.cm.ttl = 4
        with self.assertSendMainboard("M666H242", "G30X0Y0") as executor:
            self.cm.start(executor)
            self.cm.on_command_empty(executor)

        for sb in (1, -1, 1):
            if sb > 0:
                m666 = "M666H241.2000"
                zprob = "Bed Z-Height at X:-73.6122 Y:-42.5 = 0.8"
            else:
                m666 = "M666H242.0000"
                zprob = "Bed Z-Height at X:-73.6122 Y:-42.5 = -0.8"

            with self.assertSendMainboard(m666, "G30X0Y0") as executor:
                self.cm.on_mainboard_message(zprob, executor)
                self.cm.on_command_empty(executor)

        # Calculate
        self.assertIsNone(self.callback_status)
        with self.assertSendMainboard("M666H242.0000",
                                      "G1F6000X0Y0Z210") as executor:
            self.cm.on_mainboard_message(
                "Bed Z-Height at X:-73.6122 Y:-42.5 = -0.8", executor)
            self.assertRaises(RuntimeError, self.cm.on_command_empty, executor)

    def test_zprob_failed(self):
        with self.assertSendMainboard("M666H242", "G30X0Y0",
                                      "G1F6000X0Y0Z210") as executor:
            self.cm.start(executor)
            self.cm.on_command_empty(executor)
            self.assertRaises(RuntimeError, self.cm.on_mainboard_message,
                              "Bed Z-Height at X:-73.6122 Y:-42.5 = -100",
                              executor)
