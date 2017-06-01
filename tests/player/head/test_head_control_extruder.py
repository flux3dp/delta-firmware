
from unittest import TestCase
import socket

from fluxmonitor.player.head_controller import HeadController
from .sharedlib import SharedTestCase, nan


HELLO_CMD = "1 HELLO *115\n"
EXTRUDER_HELLO_RESP_DICT = {
    'VENDOR': 'FLUX .inc', 'MAX_TEMPERATURE': '235.0', 'FIRMWARE': 'OHMAMA',
    'VERSION': '1.0922', 'TYPE': 'EXTRUDER', 'ID': '1572870', 'EXTRUDER': 1}
EXTRUDER_HELLO_RESP = (
    "1 OK HELLO TYPE:EXTRUDER ID:1572870 VENDOR:FLUX\ .inc "
    "FIRMWARE:OHMAMA VERSION:1.0922 EXTRUDER:1 "
    "MAX_TEMPERATURE:235.0 *85\n")


PING_CMD = "1 PING *33\n"
ST_DICT = {
    "TNANR40": {'module': 'EXTRUDER', 'rt': (40.0,), 'FA': '0', 'tt': (nan,)},
    "T0R40": {'module': 'EXTRUDER', 'rt': (40.0,), 'FA': '0', 'tt': (0.0,)},
    "T0R210": {'module': 'EXTRUDER', 'rt': (210.0,), 'FA': '0', 'tt': (0.0,)},
}
PONG_EXR = {
    "ER8": "1 OK PONG ER:8 RT:169.9 TT:170.0 FA:0 *28\n",
    "TNANR40": "1 OK PONG ER:0 RT:40.0 TT:NAN FA:0 *78\n",
    "T0R40": "1 OK PONG ER:0 RT:40.0 TT:0 FA:0 *63\n",
    "T0R210": "1 OK PONG ER:0 RT:210.0 TT:0 FA:0 *8\n",
    "T210R40": "1 OK PONG ER:0 RT:40.0 TT:210.0 FA:0 *34\n",
    "T210R210": "1 OK PONG ER:0 RT:210.0 TT:210.0 FA:0 *21\n",
}

FAN_0_0 = "1 F:0 S:0 *4\n"
FAN_OK = "1 OK FAN *92\n"
HEAT_0_200_CMD = "1 H:0 T:200.0 *17\n"
HEAT_0_210_CMD = "1 H:0 T:210.0 *16\n"
HEAT_0_0_CMD = "1 H:0 T:0.0 *19\n"
HEAT_OK = "1 OK HEATER *26\n"


class ExtruderGeneralTest(SharedTestCase):
    def setUp(self):
        SharedTestCase.setUp(self)
        self.t = HeadController(self.rsock.fileno(),
                                required_module="EXTRUDER")

    def _bootstrap(self):
        def callback(caller):
            self.callback_log.append(("boot", callback))

        self.callback_log = []
        self.t.bootstrap(callback)
        self.assertRecv(HELLO_CMD)
        self.send_and_process(EXTRUDER_HELLO_RESP)
        self.assertEqual(self.callback_log, [("boot", callback)])
        self.assertTrue(self.t.sendable())

    def _recover(self, cmd_queue, resp_queue):
        def callback(caller):
            self.callback_log.append(("recover", callback))

        self.callback_log = []
        self.t.recover(callback)
        while cmd_queue:
            self.assertEqual(self.callback_log, [])
            cmd = cmd_queue.pop(0)
            self.assertRecv(cmd)
            self.send_and_process(resp_queue.pop(0))
        self.assertEqual(self.callback_log, [("recover", callback)])

    def _standby(self, cmd_queue, resp_queue):
        def callback(caller):
            self.callback_log.append(("standby", callback))

        self.callback_log = []
        self.t.standby(callback)
        while cmd_queue:
            self.assertEqual(self.callback_log, [])
            cmd = cmd_queue.pop(0)
            self.assertRecv(cmd)
            self.send_and_process(resp_queue.pop(0))
        self.assertEqual(self.callback_log, [("standby", callback)])

    def _respcmd(self, recv_cmd, resp):
        def callback(caller):
            self.callback_log.append(("respcmd", callback))

        self.callback_log = []
        self.t.set_command_callback(callback)
        self.assertRecv(recv_cmd)
        self.send_and_process(resp)
        self.assertTrue(self.t.sendable())
        self.assertEqual(self.callback_log, [("respcmd", callback)])

    def test_bootstrap_recover_standby(self):
        self.assertRaises(RuntimeError, self.t.ext.set_heater, 0, 100)

        self._bootstrap()
        self.assertTrue(self.t.sendable())
        self.assertEqual(self.t.profile, EXTRUDER_HELLO_RESP_DICT)

        self.t.ext.set_heater(0, 200)
        self.assertRecv(HEAT_0_200_CMD)
        self.send_and_process(HEAT_OK)
        self.assertTrue(self.t.sendable())

        self._bootstrap()
        self._recover(cmd_queue=[HEAT_0_200_CMD], resp_queue=[HEAT_OK])
        self._standby(cmd_queue=[FAN_0_0, HEAT_0_0_CMD],
                      resp_queue=[FAN_OK, HEAT_OK])
        self._recover(cmd_queue=[HEAT_0_200_CMD], resp_queue=[HEAT_OK])

    def test_ping_pong(self):
        self._bootstrap()
        self.t.patrol()
        self.assertRecv(PING_CMD)
        self.send_and_process(PONG_EXR["TNANR40"])
        self.assertEqual(self.t.status, ST_DICT["TNANR40"])
        self.send_and_process(PONG_EXR["T0R210"])
        self.assertEqual(self.t.status, ST_DICT["T0R210"])
        self.send_and_process(PONG_EXR["T0R40"])
        self.assertEqual(self.t.status, ST_DICT["T0R40"])
        self.send_and_process(PONG_EXR["T0R210"])
        self.assertEqual(self.t.status, ST_DICT["T0R210"])

    def test_hello_offline(self):
        self.t.bootstrap(None)
        self.assertRecv(HELLO_CMD)

        retry = 3
        for i in range(retry):
            self.t.send_timestamp = 0
            self.t.patrol()
            self.assertRecv(HELLO_CMD)

        self.t.send_timestamp = 0
        self.assertRaises(RuntimeError, self.t.patrol)
        self.assertFalse(self.t.sendable())

    def test_ping_offline(self):
        self._bootstrap()
        self.t.patrol()
        self.assertRecv(PING_CMD)

        retry = 3
        for i in range(retry):
            self.t.send_timestamp = 0
            self.t.patrol()
            self.assertRecv(PING_CMD)

        self.t.send_timestamp = 0
        self.assertRaises(RuntimeError, self.t.patrol)
        self.assertFalse(self.t.sendable())
        self.assertRaises(RuntimeError, self.t.ext.set_heater, 0, 100)

    def test_error_code(self):
        self._bootstrap()
        self.assertEqual(self.t.error_code, 0)

        self.t.patrol()
        self.assertRecv(PING_CMD)
        self.send_and_process(PONG_EXR["ER8"])
        self.assertEqual(self.t.error_code, 8)
        self.assertTrue(self.t.sendable())

    def test_command_callback(self):
        self._bootstrap()

        self.t.ext.set_heater(0, 200)
        self._respcmd(HEAT_0_200_CMD, HEAT_OK)

    def test_allset(self):
        self._bootstrap()

        def callback(caller):
            self.callback_log.append(("allset", callback))

        # allset=False, Update TT:nan, RT:40.0
        self.t.patrol()
        self.assertRecv(PING_CMD)
        self.send_and_process(PONG_EXR["TNANR40"])
        self.assertTrue(self.t.ext.allset())

        self.t.set_allset_callback(callback)

        # Update TT: 210
        self.t.ext.set_heater(0, 210)
        self._respcmd(HEAT_0_210_CMD, HEAT_OK)
        self.callback_log = []
        self.assertFalse(self.t.ext.allset())

        # allset=False, Update TT:210, RT:40.0
        self.t.lastupdate = 0
        self.t.patrol()
        self.assertRecv(PING_CMD)
        self.send_and_process(PONG_EXR["T210R40"])
        self.assertFalse(self.t.ext.allset())
        self.assertEqual(self.callback_log, [])

        # allset=True, Update TT:210, RT:210.0
        self.send_and_process(PONG_EXR["T210R210"])
        self.assertTrue(self.t.ext.allset())
        self.assertEqual(self.callback_log, [("allset", callback)])

    def test_cmd_timeout(self):
        self._bootstrap()
        self.t.ext.set_heater(0, 210)
        self.assertRecv(HEAT_0_210_CMD)

        for i in range(3):
            self.t.send_timestamp = 0
            self.t.patrol()
            self.assertRecv(HEAT_0_210_CMD)

        self.t.send_timestamp = 0
        self.assertRaises(RuntimeError, self.t.patrol)
        self.assertFalse(self.t.sendable())


class ToolheadIOErrorTest(TestCase):
    def test_send_hello_error(self):
        self.t = HeadController(1000, required_module="EXTRUDER")
        self.assertRaises(IOError, self.t.bootstrap)

    def test_send_ping_error(self):
        s1, s2 = socket.socketpair()
        t = HeadController(s2.fileno(), required_module="EXTRUDER")
        t.bootstrap()
        s1.send(EXTRUDER_HELLO_RESP)
        t.handle_recv()

        s2.close()
        self.assertRaises(IOError, t.patrol)

    def test_send_command_error(self):
        s1, s2 = socket.socketpair()
        t = HeadController(s2.fileno(), required_module="EXTRUDER")
        t.bootstrap()
        s1.send(EXTRUDER_HELLO_RESP)
        t.handle_recv()

        s2.close()
        self.assertRaises(IOError, t.ext.set_heater, 0, 210)

    def test_recv_error(self):
        t = HeadController(1000, required_module="EXTRUDER")
        self.assertRaises(IOError, t.handle_recv)
