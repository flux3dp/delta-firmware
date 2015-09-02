
from tempfile import TemporaryFile
from hashlib import md5
from random import random
import unittest

from fluxmonitor.controller.tasks.misc import TaskLoader


class TaskLoaderTest(unittest.TestCase):
    def test_loder_task(self):
        f = TemporaryFile()
        h1 = md5()
        for i in xrange(8192):
            buf = ("%04i %.8f\n" % (i, random())).encode()
            h1.update(buf)
            f.write(buf)

        f.seek(0)

        t = TaskLoader(f)
        h2 = md5()
        while True:
            buf = t.readline()
            # print(buf)
            if buf:
                h2.update(buf)
            else:
                break

        self.assertEqual(h1.hexdigest(), h2.hexdigest())
