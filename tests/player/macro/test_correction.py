
from fluxmonitor.player.macro.correction import CorrectionMacro
from fluxmonitor.storage import Metadata

from tests.player.misc import ControlTestBase


class CorrectionMacroTest(ControlTestBase):
    def on_success_callback(self):
        self.assertIsNone(self.callback_status)
        self.callback_status = "OK"

    def on_error_callback(self, err_code):
        self.assertIsNone(self.callback_status)
        self.callback_status = err_code

    def reset_callback(self):
        self.callback_status = None

    def setUp(self):
        self.meta = Metadata()
        self.reset_callback()
        self.meta.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 242}
        self.cm = CorrectionMacro(self.on_success_callback)

    def tearDown(self):
        self.meta = None

    def test_simple_run(self):
        # # ROUND 0
        # Move to point 1
        with self.assertSendMainboard("M666H242",
                                      "G30X-73.6122Y-42.5") as executor:
            self.cm.start(executor)
            self.cm.on_command_empty(executor)
        # Get point 1 z
        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0.3", executor)
        self.assertEqual(self.cm.data, [0.3])

        # Move to point 2
        with self.assertSendMainboard("G30X73.6122Y-42.5") as executor:
            self.cm.on_command_empty(executor)
        # Get point 2 z
        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0.25", executor)
        self.assertEqual(self.cm.data, [0.3, 0.25])

        # Move to point 3
        with self.assertSendMainboard("G30X0Y85") as executor:
            self.cm.on_command_empty(executor)
        # Get point 3 z
        with self.assertSendMainboard() as executor:
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0.31", executor)
        self.assertEqual(self.cm.data, [0.3, 0.25, 0.31])

        # # Calculate
        with self.assertSendMainboard("M666X-0.0100Y-0.0640Z-0.0000",
                                      "G30X-73.6122Y-42.5") as executor:
            self.cm.on_command_empty(executor)
            self.assertEqual(self.cm.round, 1)

        # # ROUND 1
        with self.assertSendMainboard("G30X-73.6122Y-42.5",
                                      "G30X73.6122Y-42.5",
                                      "G30X0Y85") as executor:
            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0.01", executor)

            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "DATA ZPROBE -0.01", executor)

            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0.02", executor)

        # # Calculate
        self.assertIsNone(self.callback_status)
        with self.assertSendMainboard("G1F9000X0Y0Z30") as executor:
            self.cm.on_command_empty(executor)  # Send G28
            self.cm.on_command_empty(executor)
            self.assertEqual(self.callback_status, "OK")

    def test_failed_run(self):
        self.cm.ttl = 1
        with self.assertSendMainboard("M666H242",
                                      "G30X-73.6122Y-42.5",
                                      "G30X73.6122Y-42.5",
                                      "G30X0Y85") as executor:
            self.cm.start(executor)
            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "DATA ZPROBE 5", executor)
            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0", executor)
            self.cm.on_command_empty(executor)
            self.cm.on_mainboard_message(
                "DATA ZPROBE 0", executor)

        # # Calculate
        self.assertIsNone(self.callback_status)
        with self.assertSendMainboard("M666X0Y0Z0H242", "G1F10000X0Y0Z230",
                                      "G28+") as executor:
            self.assertRaises(RuntimeError, self.cm.on_command_empty, executor)
