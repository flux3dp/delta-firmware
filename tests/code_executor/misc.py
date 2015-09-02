
import unittest


class ControlTestBase(unittest.TestCase):
    _send_headboard_sequence = None
    _send_mainboard_sequence = None

    def raiseException(self, sender):
        raise RuntimeWarning("UNITTEST")

    def send_headboard(self, msg):
        if not self._send_headboard_sequence:
            raise AssertionError("send_mainboard message queue is empty, use "
                                 "setHeadboardSendSequence preset excepted "
                                 "send_maiboard call. (Recive %s)" % repr(msg))

        match = self._send_headboard_sequence.pop(0)
        self.assertEqual(msg, match)

    def setHeadboardSendSequence(self, *args):
        self._send_headboard_sequence = list(args)

    def assertSendHeadboardCalled(self):
        self.assertItemsEqual(self._send_headboard_sequence, ())

    def assertSendMainboard(self, *args):
        return AssertControllerSendHelper(self, mainboard_send_sequence=args)


class AssertControllerSendHelper(object):
    mseq = hseq = None

    def __init__(self, test_case, mainboard_send_sequence=None,
                 headboard_send_sequence=None):
        self.tc = test_case
        if mainboard_send_sequence:
            self.mseq = list(mainboard_send_sequence)
        if headboard_send_sequence:
            self.hseq = list(headboard_send_sequence)

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
