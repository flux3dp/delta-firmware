
import unittest
from fluxmonitor.code_executor.misc import TaskLoader
from tests.fixtures import Fixtures
import os


class TaskLoaderTest(unittest.TestCase):
    def test_loader(self):
        f = Fixtures.fcodes.open("print_simple_move.fcode", "rb")
        t = TaskLoader(f)
        # import IPython
        # IPython.embed()
        readlen = 0

        self.assertTrue(t.is_alive())
        while readlen < t.script_size:
            buf = os.read(t.fileno(), 4096)
            if len(buf):
                readlen += len(buf)
            else:
                raise RuntimeError("EOF?")

        if os.read(t.fileno(), 4096):
            raise RuntimeError("Not EOF?")

        t.close()
        t.join(1)
        self.assertFalse(t.is_alive())

