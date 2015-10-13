
import logging
import socket
import re

from fluxmonitor.code_executor.main_controller import MainController
from fluxmonitor.config import uart_config
from fluxmonitor.err_codes import RESOURCE_BUSY, UNKNOW_COMMAND

from .base import CommandMixIn, ExclusiveMixIn, DeviceOperationMixIn, \
    DeviceMessageReceiverMixIn

RE_REPORT_DIST = re.compile("X:(?P<X>(-)?[\d]+(.[\d]+)?) "
                            "Y:(?P<Y>(-)?[\d]+(.[\d]+)?) "
                            "Z:(?P<Z>(-)?[\d]+(.[\d]+)?) ")
logger = logging.getLogger(__name__)



def check_mainboard(method):
    def wrap(self, sender):
        if self._ready & 1:
            return method(self, sender)
        else:
            raise RuntimeError(RESOURCE_BUSY, "Mainboard not ready")
    return wrap


class MaintainTask(ExclusiveMixIn, CommandMixIn, DeviceOperationMixIn,
                   DeviceMessageReceiverMixIn):
    def __init__(self, server, sock):
        self._ready = 0
        self._busy = False
        self._mainboard_msg_filter = None

        self.server = server
        self.connect()
        self.main_ctrl = MainController(
            executor=self, bufsize=14,
            ready_callback=self._on_mainboard_ready,
        )

        ExclusiveMixIn.__init__(self, server, sock)
        self.server.add_loop_event(self)

    def on_exit(self, sender):
        self.main_ctrl.close(self)
        self.server.remove_loop_event(self)
        self.disconnect()

    def _on_mainboard_ready(self, ctrl):
        self._ready |= 1

    def send_mainboard(self, msg):
        if self._uart_mb.send(msg) != len(msg):
            raise Exception("DIE")

    def send_headboard(self, msg):
        self._uart_mb.send(msg)

    def on_mainboard_message(self, sender):
        for msg in self.recv_from_mainboard(sender):
            if self._mainboard_msg_filter:
                self._mainboard_msg_filter(msg)
            self.main_ctrl.on_message(msg, self)

    def on_headboard_message(self, sender):
        for msg in self.recv_from_headboard(sender):
            pass

    def dispatch_cmd(self, cmd, sock):
        if self._busy:
            raise RuntimeError(RESOURCE_BUSY)

        if cmd == "home":
            return self.do_home(sock)
        elif cmd == "eadj":
            return self.do_eadj(sock)

        elif cmd == "madj":
            return self.do_madj(sock)

        elif cmd == "reset_mb":
            s = socket.socket(socket.AF_UNIX)
            s.connect(uart_config["control"])
            s.send(b"reset mb")
            s.close()
            return "ok"

        elif cmd == "quit":
            self.server.exit_task(self)
            return "ok"
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    @check_mainboard
    def do_home(self, sender):
        def callback(ctrl):
            self._busy = False
            sender.send_text("ok")
        self.main_ctrl.callback_msg_empty = callback
        self.main_ctrl.send_cmd("G28", self)
        self._busy = True

    @check_mainboard
    def do_eadj(self, sender):
        data = []

        def send_m119(main_ctrl):
            try:
                self.main_ctrl.send_cmd("M119", self)
                self.main_ctrl.send_cmd("G4P300", self)
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage1_chk_zprop_triggered(msg):
            try:
                if msg == "z_probe: TRIGGERED":
                    self._mainboard_msg_filter = stage2_chk_zprop_nontriggered
                    logger.debug("%s... OK", msg)
                elif msg == "z_probe: NOT TRIGGERED":
                    sender.send_text("NEED_ZPROBE_TRIGGERED")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage2_chk_zprop_nontriggered(msg):
            try:
                if msg == "z_probe: NOT TRIGGERED":
                    self.main_ctrl.callback_msg_empty = None
                    self._mainboard_msg_filter = stage3_test_x
                    logger.debug("%s... OK", msg)
                    self.main_ctrl.send_cmd("G28", self)
                    self.main_ctrl.send_cmd("G30X-73.6122Y-42.5", self)

                    sender.send_text("TEST_X")
                elif msg == "z_probe: TRIGGERED":
                    sender.send_text("NEED_ZPROBE_NOT_TRIGGERED")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage3_test_x(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)
                    self.main_ctrl.send_cmd("G30X73.6122Y-42.5", self)
                    self._mainboard_msg_filter = stage4_test_y

                    sender.send_text("TEST_Y")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage4_test_y(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)
                    self.main_ctrl.send_cmd("G30X0Y85", self)
                    self._mainboard_msg_filter = stage5_test_z

                    sender.send_text("TEST_Z")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage5_test_z(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)
                    self.main_ctrl.send_cmd("G30X0Y0", self)
                    self._mainboard_msg_filter = stage6_test_h

                    sender.send_text("TEST_H")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage6_test_h(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    self._mainboard_msg_filter = None
                    self._busy = False

                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)

                    sender.send_text("DATA %s" % data)
                    sender.send_text("ok")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        self.main_ctrl.send_cmd("M84", self)

        self._busy = True
        send_m119(self.main_ctrl)
        self.main_ctrl.callback_msg_empty = send_m119
        self._mainboard_msg_filter = stage1_chk_zprop_triggered
        return "continue"

    @check_mainboard
    def do_madj(self, sender):
        data = []

        def send_cmd(x, y):
            cmds = ("G28", "G1F8000Z100",
                    "G1F8000X%.5fY%.5fZ60" % (x, y),
                    "X3O", "G1F1000Z10", "G1F500Z5", "G1F300Z-2", "X3F",
                    "M84", "G4P50", "X6")
            for c in cmds:
                self.main_ctrl.send_cmd(c, self)

        def stage1_test_x(msg):
            try:
                sender.send_text("TESTING_X")

                m = RE_REPORT_DIST.match(msg)
                if m:
                    data.append(m.groupdict())

                    self._mainboard_msg_filter = stage2_test_y
                    send_cmd(73.6122, -42.5)

            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage2_test_y(msg):
            try:
                sender.send_text("TESTING_Y")

                m = RE_REPORT_DIST.match(msg)
                if m:
                    data.append(m.groupdict())

                    self._mainboard_msg_filter = stage3_test_z
                    send_cmd(0, 85)

            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage3_test_z(msg):
            try:
                sender.send_text("TESTING_Z")

                m = RE_REPORT_DIST.match(msg)
                if m:
                    data.append(m.groupdict())

                    self._mainboard_msg_filter = stage4_test_h
                    send_cmd(0, 0)

            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        def stage4_test_h(msg):
            try:
                sender.send_text("TESTING_H")

                m = RE_REPORT_DIST.match(msg)
                if m:
                    data.append(m.groupdict())
                    self._mainboard_msg_filter = None
                    self._busy = False

                    for resule in data:
                        logger.debug("DATA: %s", data)
                        sender.send_text("DATA %(X)s, %(Y)s, %(Z)s" %
                                         resule)

                    sender.send_text("ok")
            except Exception:
                logger.exception("Unhandle Error")
                self.server.exit_task(self)

        self._busy = True
        self.main_ctrl.send_cmd("G90", self)
        send_cmd(-73.6122, -42.5)
        self._mainboard_msg_filter = stage1_test_x

        return "continue"

    def on_loop(self, loop):
        try:
            self.main_ctrl.patrol(self)
        except SystemError:
            self.server.exit_task(self)
