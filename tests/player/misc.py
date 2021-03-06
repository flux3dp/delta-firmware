
import unittest


class ControlTestBase(unittest.TestCase):
    _send_headboard_sequence = None
    _send_mainboard_sequence = None

    def raiseException(self, sender):
        raise UnittestError("UNITTEST")

    def get_executor(self):
        return SendHelper()

    def assertSendHeadboard(self, *args):
        return AssertControllerSendHelper(self, headboard_send_sequence=args)

    def assertSendMainboard(self, *args):
        return AssertControllerSendHelper(self, mainboard_send_sequence=args)


class SendHelper(object):
    def send_headboard(self, msg):
        pass

    def send_mainboard(self, msg):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass


class AssertControllerSendHelper(object):
    mseq = hseq = None

    def __init__(self, test_case, mainboard_send_sequence=None,
                 headboard_send_sequence=None):
        self.tc = test_case
        if mainboard_send_sequence:
            self.mseq = list(mainboard_send_sequence)
        if headboard_send_sequence:
            self.hseq = list(headboard_send_sequence)
        self.main_ctrl = Hook(self.send_mainboard)

    def send_headboard(self, msg):
        if self.hseq:
            match = self.hseq.pop(0)
            self.tc.assertEqual(msg, match)
        else:
            raise AssertionError(
                "Headboard send non-excepted message: %s" % repr(msg))

    def send_mainboard(self, msg):
        if self.mseq:
            match = self.mseq.pop(0)
            self.tc.assertEqual(msg, match)
        else:
            raise AssertionError(
                "Mainboard send non-excepted message: %s" % repr(msg))

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if type:
            pass
        else:
            if self.mseq:
                raise AssertionError("Mainboard does not send: %s" % self.mseq)
            if self.hseq:
                raise AssertionError("Headboard does not send: %s" % self.hseq)


class Hook(object):
    def __init__(self, cb):
        self._cb = cb

    def send_cmd(self, msg, _):
        self._cb(msg)


class UnittestError(Exception):
    pass
