
from select import select
from time import time, sleep
import unittest
import socket

from fluxmonitor.player.base import ST_ABORTED
from fluxmonitor.player.fcode_executor import FcodeExecutor

from tests.fixtures import Fixtures
from tests import TEST_FLAGS


class CodeExecutorTest(unittest.TestCase):
    def setUp(self):
        self.mainboard, self.mainboard_endpoint = socket.socketpair()
        self.headboard, self.headboard_endpoint = socket.socketpair()
        self.taskfile, self.taskfile_endpoint = socket.socketpair()
        self.mainboard.settimeout(0)
        self.headboard.settimeout(0)
        self.taskfile.settimeout(0)
        self.mainboard_endpoint.settimeout(0)
        self.headboard_endpoint.settimeout(0)
        self.taskfile_endpoint.settimeout(0)

        if "debug" in TEST_FLAGS:
            print("")

    def tearDown(self):
        self.mainboard.close()
        self.mainboard_endpoint.close()
        self.headboard.close()
        self.headboard_endpoint.close()
        self.taskfile.close()
        self.taskfile_endpoint.close()

    def start_with_input(self, filename):
        self.ex = FcodeExecutor(
            self.mainboard, self.headboard,
            Fixtures.fcodes.open(filename, "rb"))

    def send_to_mainboard(self, msg):
        if "debug" in TEST_FLAGS:
            print("{:>49} < |{:<26}".format(msg, " "))
        self.ex.on_mainboard_message(msg)

    def send_to_headboard(self, msg):
        if "debug" in TEST_FLAGS:
            print("{:<52}|{:>23} < ".format(" ", msg))
        self.ex.on_headboard_message(msg)

    def read_from_mainboard(self):
        while select((self.mainboard_endpoint, ), (), (), 0)[0]:
            for m in self.mainboard_endpoint.recv(4096).strip("\n").split("\n"):
                if "debug" in TEST_FLAGS:
                    print(" > {:<49}|{:<26}".format(m, " "))
                yield m

    def read_from_headboard(self):
        while select((self.headboard_endpoint, ), (), (), 0)[0]:
            for m in self.headboard_endpoint.recv(4096).strip("\n").split("\n"):
                if "debug" in TEST_FLAGS:
                    print("{:<52}| > {:<23}".format(" ", m))
                yield m

    @unittest.skipUnless("lengthy" in TEST_FLAGS, "Run with TEST=\"lengthy\"")
    def test_mainboard_launch_timeout(self):
        self.start_with_input("print_simple_move.fcode")
        start_at = time()
        while True:
            rl = select((self.mainboard_endpoint, self.headboard_endpoint), (), (), 1)[0]
            for r in rl:
                buf = r.recv(4096)
                if buf == b"R\n":
                    self.ex.on_headboard_message(b"FLUX Printer Module")
                elif buf.startswith(b"F"):
                    self.ex.on_headboard_message(b"ok@" + buf)

            self.ex.on_loop(self)

            if self.ex.get_status()["status"] == ST_ABORTED:
                if not self.ex.head_ctrl.ready:
                    raise RuntimeError("Headboard not ready")
                break
            elif time() - start_at > 4.5:
                raise RuntimeError("Mainboard timeout not raised")

            sleep(0.05)

    @unittest.skipUnless("lengthy" in TEST_FLAGS, "Run with TEST=\"lengthy\"")
    def test_headboard_launch_timeout(self):
        self.start_with_input("print_simple_move.fcode")
        start_at = time()
        select_args = ((self.mainboard_endpoint,
                        self.headboard_endpoint), (), (), 1)
        while True:
            rl = select(*select_args)[0]
            for r in rl:
                if r.recv(4096) == b"C1O\n":
                    self.ex.on_mainboard_message(b"CTRL LINECHECK_ENABLED")
            self.ex.on_loop(self)

            if self.ex.get_status()["status"] in [ST_PAUSED, ST_PAUSING]:
                if not self.ex.main_ctrl.ready:
                    raise RuntimeError("Mainboard not ready")
                break
            elif time() - start_at > 6.0:
                raise RuntimeError("Headboard timeout not raised")
            sleep(0.05)

    @unittest.skipUnless("flow" in TEST_FLAGS or "flow_simple" in TEST_FLAGS,
                         "Run with TEST=\"flow\" or \"flow_simple\"")
    def test_run_simple(self):
        self.start_with_input("print_simple_move.fcode")
        select_args = ((self.mainboard_endpoint,
                        self.headboard_endpoint), (), (), 1)
        ln_ts = time()
        ln_recv = 0
        ln_done = 0

        self.ex.debug = True
        st = self.ex._status
        if "debug" in TEST_FLAGS:
            print(" >>> %s <<<" % st)

        while True:
            for m in self.read_from_mainboard():
                if m == "C1O":
                    self.send_to_mainboard(b"CTRL LINECHECK_ENABLED")
                else:
                    self.send_to_mainboard(b"LN %i %i" % (ln_recv + 1,
                                                          ln_recv - ln_done))
                    ln_recv += 1
                    while ln_recv - ln_done > 8:
                        self.send_to_mainboard(b"ok")
                        ln_done += 1
                        ln_ts = time()

            if ln_recv - ln_done > 0 and time() - ln_ts > 0.1:
                self.send_to_mainboard(b"ok")
                ln_done += 1
                ln_ts = time()

            for m in self.read_from_headboard():
                if m == b"R":
                    self.send_to_headboard(b"FLUX Printer Module")
                elif m == b"T":
                    self.send_to_headboard(b" abc: 123 >>> 500")
                else:
                    self.send_to_headboard(b"ok@%s" % m)

            self.ex.on_loop(self)
            if self.ex._status != st:
                st = self.ex._status
                if "debug" in TEST_FLAGS:
                    print(" >>> %s <<< %s" % (st, self.ex._err_symbol))
                if st == ST_COMPLETED:
                    return

    @unittest.skipUnless("flow" in TEST_FLAGS or "flow_heating" in TEST_FLAGS,
                         "Run with TEST=\"flow\" or \"flow_heating\"")
    def test_run_heating(self):
        self.start_with_input("print_with_wait_temp.fcode")
        select_args = ((self.mainboard_endpoint,
                        self.headboard_endpoint), (), (), 1)
        ln_ts = time()
        ln_recv = 0
        ln_done = 0
        t_counter = 0

        self.ex.debug = True
        st = self.ex._status
        if "debug" in TEST_FLAGS:
            print(" >>> %s <<<" % st)

        while True:
            for m in self.read_from_mainboard():
                if m == "C1O":
                    self.send_to_mainboard(b"CTRL LINECHECK_ENABLED")
                else:
                    self.send_to_mainboard(b"LN %i %i" % (ln_recv + 1,
                                                          ln_recv - ln_done))
                    ln_recv += 1
                    while ln_recv - ln_done > 8:
                        self.send_to_mainboard(b"ok")
                        ln_done += 1
                        ln_ts = time()

            if ln_recv - ln_done > 0 and time() - ln_ts > 0.1:
                self.send_to_mainboard(b"ok")
                ln_done += 1
                ln_ts = time()

            for m in self.read_from_headboard():
                if m == b"R":
                    self.send_to_headboard(b"FLUX Printer Module")
                elif m == b"T":
                    t_counter += 1
                    temp = min(2000, t_counter * 500)
                    self.send_to_headboard(b" abc: 123 >>> %i" % temp)
                else:
                    self.send_to_headboard(b"ok@%s" % m)

            self.ex.on_loop(self)
            if self.ex._status != st:
                st = self.ex._status
                if "debug" in TEST_FLAGS:
                    print(" >>> %s <<< %s" % (st, self.ex._err_symbol))
                if st == ST_COMPLETED:
                    return
