
import unittest
import socket
import struct

from fluxmonitor.code_executor._device_fsm import PyDeviceFSM
from tests.fixtures import Fixtures

G1F6000X41Y29Z116T0E5 = struct.pack("<Bfffff", 128 + 64 + 32 + 16 + 8 + 4,
                                    6000, 41, 29, 116, 5)
G1F6000X1T1E5 = struct.pack("<Bfff", 128 + 64 + 32 + 2, 6000, 1, 5)
G1F6000Z0 = struct.pack("<Bff", 128 + 64 + 8, 6000, 0)
G1F6000X2T0E3 = struct.pack("<Bfff", 128 + 64 + 32 + 4, 6000, 2, 3)
G1F6000X3T1E8 = struct.pack("<Bfff", 128 + 64 + 32 + 2, 6000, 3, 8)
G1X10Z0T1E5 = struct.pack("<Bfff", 128 + 32 + 8 + 2, 10, 0, 5)

G92X50Z30 = struct.pack("<Bff", 64 + 32 + 8, 50, 30)

G4P750 = struct.pack("<Bf", 4, 750)


class DeviceFSMTest(unittest.TestCase):
    def clean_queue(self):
        self.callback_queue = []

    def setUp(self):
        self.fsm = PyDeviceFSM(x=0, y=0, z=240, e1=0, e2=0, e3=0)
        self.clean_queue()
        self.input, self.output = socket.socketpair()

    def tearDown(self):
        self.input.close()
        self.output.close()

    def feed_cb(self, msg, target):
        self.callback_queue.append((target, msg))

    def test_simple_move(self):
        self.fsm.set_x(40)
        self.fsm.set_y(30)
        self.fsm.set_z(120)

        self.input.send(G1F6000X41Y29Z116T0E5)
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G1F6000X41Y29Z116T0E5))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'G1 F6000 X41.000000 Y29.000000 Z116.000000 E5.000000'),
        ))

    def test_split_move(self):
        self.input.send(G1F6000Z0)
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G1F6000Z0))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'G1 F6000 Z210.000000'),
            (1, 'G1 Z180.000000'),
            (1, 'G1 Z150.000000'),
            (1, 'G1 Z120.000000'),
            (1, 'G1 Z90.000000'),
            (1, 'G1 Z60.000000'),
            (1, 'G1 Z30.000000'),
            (1, 'G1 Z0.000000'),
        ))

    def test_move_with_change_extruder(self):
        self.input.send(G1F6000X1T1E5);
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G1F6000X1T1E5))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'T1'),
            (1, 'G92 E0.000000'),
            (1, 'G1 F6000 X1.000000 E5.000000'),
        ))
        self.clean_queue()

        self.input.send(G1F6000X2T0E3);
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G1F6000X2T0E3))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'T0'),
            (1, 'G92 E0.000000'),
            (1, 'G1 X2.000000 E3.000000'),
        ))
        self.clean_queue()

        self.input.send(G1F6000X3T1E8);
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G1F6000X3T1E8))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'T1'),
            (1, 'G92 E5.000000'),
            (1, 'G1 X3.000000 E8.000000'),
        ))
        self.clean_queue()

    def test_traveled(self):
        self.input.send(G1X10Z0T1E5);
        self.fsm.feed(self.output.fileno(), self.feed_cb)
        self.assertAlmostEqual(self.fsm.get_traveled(), 240.208242989)

    def test_set_position(self):
        self.input.send(G92X50Z30);
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G92X50Z30))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'G92 X50.000000 Z30.000000'),
        ))

    def test_sleep(self):  # G4
        self.input.send(G4P750)
        self.assertEqual(
            self.fsm.feed(self.output.fileno(), self.feed_cb),
            len(G4P750))
        self.assertItemsEqual(self.callback_queue, (
            (1, 'G4 P750'),
        ))

    def test_run_fcode(self):
        from fluxmonitor.code_executor.misc import TaskLoader
        f = Fixtures.fcodes.open("print_simple_move.fcode", "rb")
        t = TaskLoader(f)

        while self.fsm.feed(t.fileno(), self.feed_cb) > 0:
            pass

        self.assertEqual(self.callback_queue[0][1], "G28")
        self.assertEqual(self.callback_queue[-1][1], "G28")
