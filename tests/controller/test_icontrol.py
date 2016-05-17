
import unittest
import socket
import pyev

from msgpack import unpackb

from tests._utils.virtual_device import VirtualDevice, has_data
from fluxmonitor.controller.tasks.icontrol_task import (
    IControlTask, CMD_G001, CMD_G028)


class VirtualKernal(object):
    def exclusive(self, _):
        pass


class VirtualStack(object):
    def __init__(self):
        self.loop = pyev.Loop(debug=True)
        self.loop.data = VirtualKernal()

    def flush(self):
        self.loop.start(pyev.EVRUN_NOWAIT)


class RobotSocketHandler(object):
    def __init__(self, sock):
        self.sock = sock

    def send(self, buf):
        self.sock.send(buf)

    def send_text(self, txt):
        self.sock.send(txt)

    def close(self):
        raise RuntimeError("CONNECTION_CLOSE")


# Test struct
#                                                Socket
#                 Function Call           (virtual_stack.flush())
#   IControlTest ---------------> IControlTask <--------> Mainboard/Toolhead
#            ^                     |                        |
#            |                     |                        |
#            |---------------------|            Process message via simulator
#                  self.client                (virtual_device.flush_messages())
#                   (socket)


class IControlTest(unittest.TestCase):
    def setUp(self):
        self.virtual_device = VirtualDevice()
        self.virtual_stack = VirtualStack()
        self.client, client = socket.socketpair()
        self.handler = RobotSocketHandler(client)
        self.client.setblocking(False)

        self.icontrol = IControlTask(
            self.virtual_stack, self.handler,
            mb_sock=self.virtual_device.mb_sock,
            th_sock=self.virtual_device.th_sock)

        self.virtual_device.flush_messages()
        self.virtual_stack.flush()
        self.assertEqual(self.client.recv(4096), "ok")

    def tearDown(self):
        del self.virtual_device
        del self.virtual_stack
        self.client.close()
        del self.client
        del self.handler

    def assertReturn(self, b):  # noqa
        ret = unpackb(self.client.recv(4096))
        self.assertSequenceEqual(ret, b)  # IControl return not match

    def assertNoReturn(self):  # noqa
        if has_data(self.client):
            ret = unpackb(self.client.recv(4096))
            self.assertIsNone(ret)  # IControl should not return data

    def test_g001_g028_g030(self):
        # Error because G28 not set
        self.icontrol.process_cmd(self.handler, 0, CMD_G001,
                                  {"X": 3.2, "F": 10})
        self.assertReturn((0xff, 0, 0x01))

        # Send G28
        self.icontrol.process_cmd(self.handler, 0, CMD_G028)
        self.virtual_device.flush_messages(home="12.3243 1.00 200.1")
        self.virtual_stack.flush()
        self.assertReturn((CMD_G028, 0, [12.3243, 1.00, 200.1]))
        self.assertTrue(self.icontrol.known_position)

        # Send G1 (OK)
        self.icontrol.process_cmd(self.handler, 1, CMD_G001,
                                  {"X": 3.2, "F": 10})
        self.assertEqual(self.icontrol.main_ctrl.buffered_cmd_size, 1)
        self.virtual_device.flush_messages()
        self.virtual_stack.flush()
        self.assertNoReturn()

        # Send G1 (Out-of-range)
        self.icontrol.process_cmd(self.handler, 2, CMD_G001,
                                  {"X": 300.2, "F": 10})
        self.assertReturn((0xff, 2, 0x01))
