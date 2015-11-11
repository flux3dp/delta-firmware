
from shlex import split as shlex_split
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


def do_correction(x, y, z):
    if max(x, y, z) - min(x, y, z) > 3:
        raise ValueError("OVER_TOLERANCE")

    cm = CommonMetadata()
    old_corr = cm.plate_correction

    old_corr_str = "M666X%(X).4fY%(Y).4fZ%(Z).4f" % old_corr

    new_corr = correction.calculate(
        old_corr["X"], old_corr["Y"], old_corr["Z"], old_corr["H"], x, y, z, 0)
    cm.plate_correction = new_corr

    logger.debug("New correction: X%(X).4fY%(Y).4fZ%(Z).4f",
                 new_corr)

    new_corr.pop("H")

    return (
        old_corr_str,
        "M666X%(X).4fY%(Y).4fZ%(Z).4f" % new_corr
    )


def do_h_correction(delta=None, h=None):
    cm = CommonMetadata()

    if not h:
        oldh = cm.plate_correction["H"]
        h = oldh - delta

    if h > 248 or h < 230:
        logger.error("H ERROR: %f" % h)
        raise ValueError("INPUT_FAILED")

    cm.plate_correction = {"H": h}
    return "M666H%.4f" % h


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

    def dispatch_cmd(self, cmdline, sock):
        if self._busy:
            raise RuntimeError(RESOURCE_BUSY)

        params = shlex_split(cmdline)
        cmd = params[0]

        if cmd == "home":
            return self.do_home(sock)

        elif cmd == "eadj":
            clean = (len(params) > 1 and params[1] == "clean")
            return self.do_eadj(sock, clean=clean)

        elif cmd == "cor_h":
            if len(params) > 1:
                h = float(params[1])
                return self.do_h_correction(sock, h=h)
            else:
                return self.do_h_correction(sock)

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
                sender.send_text("DEBUG MB %s" % msg)
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    sender.send_text("DEBUG X: %.4f" % data[-1])
                    self.main_ctrl.send_cmd("G30X73.6122Y-42.5", self)
                    self._mainboard_msg_filter = stage2_test_y

            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        def stage2_test_y(msg):
            try:
                sender.send_text("DEBUG MB %s" % msg)
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    sender.send_text("DEBUG Y: %.4f" % data[-1])
                    self.main_ctrl.send_cmd("G30X0Y85", self)
                    self._mainboard_msg_filter = stage3_test_z

            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        def stage3_test_z(msg):
            try:
                sender.send_text("DEBUG MB %s" % msg)
                if msg.startswith("Bed Z-Height at"):
                    self._mainboard_msg_filter = None
                    self._busy = False

                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    sender.send_text("DEBUG Z: %.4f" % data[-1])

                    if clean:
                        sender.send_text("DEBUG: Clean")
                    old_cmd, new_cmd = do_correction(*data)
                    sender.send_text("DEBUG OLD --> %s" % old_cmd)
                    sender.send_text("DEBUG NEW --> %s" % new_cmd)
                    self.main_ctrl.send_cmd(new_cmd, self)

                    sender.send_text("ok %.4f %.4f %.4f" % (data[0], data[1],
                                                            data[2]))
            except ValueError as e:
                sender.send_text("error %s" % e.args[0])

            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        self._busy = True

        if clean:
            cm = CommonMetadata()
            # TODO
            cm.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 242}
            self.main_ctrl.send_cmd("M666X0Y0Z0H242", self)
            self.main_ctrl.send_cmd("G28", self)

        self._mainboard_msg_filter = stage1_test_x
        # self.main_ctrl.send_cmd("G28", self)
        self.main_ctrl.send_cmd("G30X-73.6122Y-42.5", self)
        return "continue"

    @check_mainboard
    def do_h_correction(self, sender, h=None):
        if h is not None:
            cmd = do_h_correction(h=h)
            sender.send_text("continue")
            sender.send_text("ok 0")
            return

        def stage_test_h(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    self._mainboard_msg_filter = None
                    self._busy = False

                    data = float(msg.rsplit(" ", 1)[-1])
                    sender.send_text("DEBUG H: %.4f" % data)

                    corr_cmd = do_h_correction(delta=data)
                    self.main_ctrl.send_cmd(corr_cmd, self)

                    sender.send_text("ok %.4f" % data)
            except ValueError as e:
                sender.send_text("error %s" % e.args[0])

            except Exception:
                logger.exception("Unhandle Error")
                sender.send_text("error UNKNOW_ERROR")
                self.server.exit_task(self)

        self._busy = True
        self._mainboard_msg_filter = stage_test_h
        self.main_ctrl.send_cmd("G30X0Y0", self)
        return "continue"

    def on_loop(self, loop):
        try:
            self.main_ctrl.patrol(self)
        except SystemError:
            self.server.exit_task(self)
