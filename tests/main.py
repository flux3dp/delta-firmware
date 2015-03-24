
import unittest
import os


def everything():
    return unittest.TestLoader().discover(os.path.dirname(__file__),
                                          pattern='test_*.py')


def misc():
    basedir = os.path.join(os.path.dirname(__file__), "misc")
    return unittest.TestLoader().discover(basedir,
                                          pattern='test_*.py')
