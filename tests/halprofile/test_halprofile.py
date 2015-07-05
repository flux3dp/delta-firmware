
import unittest
import platform


class HalProfileTest(unittest.TestCase):
    @unittest.skipIf(platform.uname()[0] != "Darwin", "Run on osx only")
    def test_darwin_model_id(self):
        from fluxmonitor import _halprofile
        self.assertEqual(_halprofile.model_id, "darwin-dev")

