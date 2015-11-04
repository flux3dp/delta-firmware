
import logging
import socket
import re

from fluxmonitor.code_executor.main_controller import MainController
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.misc import correction
from fluxmonitor.config import uart_config

from fluxmonitor.err_codes import RESOURCE_BUSY, UNKNOW_COMMAND

from .base import CommandMixIn, ExclusiveMixIn, DeviceOperationMixIn, \
    DeviceMessageReceiverMixIn

RE_REPORT_DIST = re.compile("X:(?P<X>(-)?[\d]+(.[\d]+)?) "
                            "Y:(?P<Y>(-)?[\d]+(.[\d]+)?) "
                            "Z:(?P<Z>(-)?[\d]+(.[\d]+)?) ")
logger = logging.getLogger(__name__)


def do_correction(x, y, z, h):
    cm = CommonMetadata()
    old_corr = cm.plate_correction
    logger.debug("Old correction: X%(X).4f Y%(Y).4f Z%(Z).4f H%(H).4f",
                 old_corr)

    new_corr = correction.calculate(
        old_corr["X"], old_corr["Y"], old_corr["Z"], old_corr["H"], x, y, z, h)
    cm.plate_correction = new_corr

    logger.debug("New correction: X%(X).4f Y%(Y).4f Z%(Z).4f H%(H).4f",
                 new_corr)

    return "M666 X%(X).4f Y%(Y).4f Z%(Z).4f H%(H).4f" % new_corr


def check_mainboard(method):
    def wrap(self, *args, **kw):
        if self._ready & 1:
            return method(self, *args, **kw)
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

        elif cmd == "eadj clean":
            return self.do_eadj(sock, clean=True)

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
    def do_eadj(self, sender, clean=False):
        data = []

        def stage1_test_x(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)
                    self.main_ctrl.send_cmd("G30X73.6122Y-42.5", self)
                    self._mainboard_msg_filter = stage2_test_y

                    sender.send_text("DEBUG: X")
            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        def stage2_test_y(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)
                    self.main_ctrl.send_cmd("G30X0Y85", self)
                    self._mainboard_msg_filter = stage3_test_z

                    sender.send_text("DEBUG: Y")
            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        def stage3_test_z(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)
                    self.main_ctrl.send_cmd("G30X0Y0", self)
                    self._mainboard_msg_filter = stage4_test_h

                    sender.send_text("DEBUG: Z")
            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        def stage4_test_h(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    self._mainboard_msg_filter = None
                    self._busy = False

                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    logger.debug("DATA: %s", data)

                    sender.send_text("DEBUG: H")
                    cmd_str = do_correction(*data)
                    self.main_ctrl.send_cmd(cmd_str, self)
                    self.main_ctrl.send_cmd("G28", self)

                    sender.send_text("DEBUG: DATA %s" % data)
                    sender.send_text("ok")
            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        self._busy = True

        if clean:
            cm = CommonMetadata()
            # TODO
            cm.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 240}
            self.main_ctrl.send_cmd("M666X0Y0Z0H240", self)

        self._mainboard_msg_filter = stage1_test_x
        self.main_ctrl.send_cmd("G28", self)
        self.main_ctrl.send_cmd("G30X-73.6122Y-42.5", self)
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
