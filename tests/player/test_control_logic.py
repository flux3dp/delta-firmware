
from fluxmonitor.player.base import BaseExecutor

import unittest


class BaseExecutorTest(unittest.TestCase):
    def test_starting_pause(self):
        ex = BaseExecutor(None, None)
        self.assertEqual(ex.status_id, 1)  # Init

        ex.start()
        self.assertEqual(ex.status_id, 4)  # Starting

        ex.pause("UT")
        self.assertEqual(ex.status_id, 4 + 32 + 2)  # Starting + Pausing

        ex.paused()
        self.assertEqual(ex.status_id, 4 + 32)  # Starting + Paused

        ex.resume()
        self.assertEqual(ex.status_id, 4 + 2)  # Starting + Resuming

        ex.resumed()
        self.assertEqual(ex.status_id, 4)  # Starting

        ex.abort("UT")
        self.assertEqual(ex.status_id, 128)  # Aborted

    def test_running_pause(self):
        ex = BaseExecutor(None, None)
        ex.start()
        ex.status_id = 16

        ex.pause("UT")
        self.assertEqual(ex.status_id, 16 + 32 + 2)  # Running + Pausing

        ex.paused()
        self.assertEqual(ex.status_id, 16 + 32)  # Running + Paused

        ex.resume()
        self.assertEqual(ex.status_id, 16 + 2)  # Running + Resuming

        ex.resumed()
        self.assertEqual(ex.status_id, 16)  # Running

        # !! Test pause while resuming
        ex.pause("UT")
        ex.paused()
        ex.resume()
        ex.pause("UT")
        self.assertEqual(ex.status_id, 16 + 32 + 2)  # Running + Pausing

        ex.abort("UT")
        self.assertEqual(ex.status_id, 128)  # Aborted

    def test_reject_pause(self):
        ex = BaseExecutor(None, None)
        ex.start()
        self.assertEqual(ex.status_id, 4)  # Starting + Pausing
        self.assertTrue(ex.pause("UT"))
        self.assertEqual(ex.status_id, 4 + 32 + 2)  # Starting + Pausing
        self.assertFalse(ex.pause("UT"))
        self.assertEqual(ex.status_id, 4 + 32 + 2)  # Starting + Pausing
        ex.paused()
        self.assertFalse(ex.pause("UT"))
        self.assertEqual(ex.status_id, 4 + 32)  # Starting + Paused
        ex.resume()
        ex.resumed()

        ex.status_id = 16
        self.assertEqual(ex.status_id, 16)  # Running + Pausing
        self.assertTrue(ex.pause("UT"))
        self.assertEqual(ex.status_id, 16 + 32 + 2)  # Running + Pausing
        self.assertFalse(ex.pause("UT"))
        self.assertEqual(ex.status_id, 16 + 32 + 2)  # Running + Pausing
        ex.paused()
        self.assertFalse(ex.pause("UT"))
        self.assertEqual(ex.status_id, 16 + 32)  # Running + Paused

        ex.abort("UT")
        self.assertFalse(ex.pause("UT"))

    def test_reject_resume(self):
        ex = BaseExecutor(None, None)
        ex.start()
        self.assertFalse(ex.resume())
        ex.pause("UT")
        self.assertFalse(ex.resume())  # Pausing, false
        ex.paused()
        self.assertTrue(ex.resume())  # Paused, true
        ex.resumed()

        ex.abort("UT")
        self.assertFalse(ex.resume())
