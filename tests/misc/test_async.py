
from errno import EAGAIN
from time import sleep

from select import select
import unittest
import socket
import os

from fluxmonitor.misc.async_signal import make_nonblock, close_fds
from fluxmonitor.misc.async_signal import read_without_error
from fluxmonitor.misc.async_signal import AsyncIO, AsyncSignal


class AsyncSingleFunctionTest(unittest.TestCase):
    def raise_exception(self, message, klass=Exception):
        raise klass(message)

    def test_make_nonblock(self):
        r, w = os.pipe()
        make_nonblock(r)

        self.assertRaises(OSError, os.read, r, 1)
        os.close(r)
        os.close(w)

    def test_close_fds(self):
        close_fds(2999, 3000)

    def test_read_without_error(self):
        r, w = os.pipe()
        make_nonblock(r)
        success, buf = read_without_error(r, 1)
        self.assertFalse(success)
        self.assertIsNone(buf)

        os.write(w, b"!")
        success, buf = read_without_error(r, 1)
        self.assertTrue(success)
        self.assertEqual(buf, b"!")

        os.close(w)
        success, buf = read_without_error(r, 1)
        self.assertTrue(success)
        self.assertEqual(buf, b"")

        os.close(r)
        self.assertRaises(OSError,
                          read_without_error,
                          r, 1)

    def test_async_signal(self):
        sig = AsyncSignal()
        rl = select((sig, ), (), (), 0.)[0]
        self.assertEqual(rl, [])

        sig.send()
        rl = select((sig, ), (), (), 0.)[0]
        self.assertEqual(rl, [sig])

        sig.send()
        sig.on_read()
        sig.on_read()

        rl = select((sig, ), (), (), 0.)[0]
        self.assertEqual(rl, [])
        sig.callback = lambda *a: self.raise_exception("Should not be call")
        sig.on_read()

        sig.close()
        self.assertRaises(OSError, sig.on_read)

    def test_async_io(self):
        def reader(sender):
            self.assertEqual(sender.obj.recv(4), b"PING")
            raise RuntimeError

        def writer(sender):
            sender.obj.send(b"PONG")

        s1, s2 = socket.socketpair()
        async_io = AsyncIO(s1, reader, writer)

        s2.send(b"PING")
        self.assertRaises(RuntimeError, async_io.on_read)
        async_io.on_write()

        s2.setblocking(False)
        self.assertEqual(s2.recv(4), b"PONG")
