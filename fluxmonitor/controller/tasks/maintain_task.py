
from shlex import split as shlex_split
import logging
import socket
import re

from fluxmonitor.player.main_controller import MainController
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.misc import correction
from fluxmonitor.config import uart_config

from fluxmonitor.err_codes import RESOURCE_BUSY, UNKNOW_COMMAND

from .base import CommandMixIn, DeviceOperationMixIn, \
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


class MaintainTask(DeviceOperationMixIn, DeviceMessageReceiverMixIn,
                   CommandMixIn):
    def __init__(self, stack, handler):
        super(MaintainTask, self).__init__(stack, handler)

        self._ready = 0
        self._busy = False
        self._mainboard_msg_filter = None

        self.main_ctrl = MainController(
            executor=self, bufsize=14,
            ready_callback=self._on_mainboard_ready,
        )

        self.timer_watcher = stack.loop.timer(1, 1, self.on_timer)
        self.timer_watcher.start()

    def on_exit(self, handler):
        self.timer_watcher.stop()
        self.timer_watcher = None
        self.main_ctrl.close(self)
        super(MaintainTask, self).on_exit(handler)

    def _on_mainboard_ready(self, ctrl):
        self._ready |= 1

    def send_mainboard(self, msg):
        if self._uart_mb.send(msg) != len(msg):
            raise Exception("DIE")

    def send_headboard(self, msg):
        self._uart_mb.send(msg)

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(1024)
            if not buf:
                logger.error("Mainboard connection broken")
                self.stack.exit_task(self)

            for msg in self.recv_from_mainboard(buf):
                if self._mainboard_msg_filter:
                    self._mainboard_msg_filter(msg)
                self.main_ctrl.on_message(msg, self)
        except Exception:
            logger.exception("Unhandle Error")

    def on_headboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(1024)
            if not buf:
                logger.error("Headboard connection broken")
                self.stack.exit_task(self)

            for msg in self.recv_from_headboard(buf):
                pass
        except Exception:
            logger.exception("Unhandle Error")

    def dispatch_cmd(self, handler, cmd, *args):
        if self._busy:
            raise RuntimeError(RESOURCE_BUSY)

        if cmd == "home":
            self.do_home(handler)

        elif cmd == "eadj":
            clean = "clean" in args
            self.do_eadj(handler, clean=clean)

        elif cmd == "cor_h":
            if len(args) > 1:
                h = float(args[1])
                self.do_h_correction(handler, h=h)
            else:
                self.do_h_correction(handler)

        elif cmd == "madj":
            self.do_madj(handler)

        elif cmd == "reset_mb":
            s = socket.socket(socket.AF_UNIX)
            s.connect(uart_config["control"])
            s.send(b"reset mb")
            s.close()
            handler.send_text("ok")

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    @check_mainboard
    def do_home(self, sender):
        def callback(ctrl):
            self._busy = False
            self.main_ctrl.callback_msg_empty = None
            sender.send_text("ok")

        self.main_ctrl.callback_msg_empty = callback
        self.main_ctrl.send_cmd("G28", self)
        self._busy = True

    @check_mainboard
    def do_eadj(self, handler, clean=False):
        data = []

        def stage1_test_x(msg):
            try:
                handler.send_text("DEBUG MB %s" % msg)
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    handler.send_text("DEBUG X: %.4f" % data[-1])
                    self.main_ctrl.send_cmd("G30X73.6122Y-42.5", self)
                    self._mainboard_msg_filter = stage2_test_y

            except Exception:
                logger.exception("Unhandle Error")
                handler.send_text("error UNKNOW_ERROR")
                self.stack.exit_task(self)

        def stage2_test_y(msg):
            try:
                handler.send_text("DEBUG MB %s" % msg)
                if msg.startswith("Bed Z-Height at"):
                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    handler.send_text("DEBUG Y: %.4f" % data[-1])
                    self.main_ctrl.send_cmd("G30X0Y85", self)
                    self._mainboard_msg_filter = stage3_test_z

            except Exception:
                logger.exception("Unhandle Error")
                handler.send_text("error UNKNOW_ERROR")
                self.stack.exit_task(self)

        def stage3_test_z(msg):
            try:
                handler.send_text("DEBUG MB %s" % msg)
                if msg.startswith("Bed Z-Height at"):
                    self._mainboard_msg_filter = None
                    self._busy = False

                    data.append(float(msg.rsplit(" ", 1)[-1]))
                    handler.send_text("DEBUG Z: %.4f" % data[-1])

                    if clean:
                        handler.send_text("DEBUG: Clean")
                    old_cmd, new_cmd = do_correction(*data)
                    handler.send_text("DEBUG OLD --> %s" % old_cmd)
                    handler.send_text("DEBUG NEW --> %s" % new_cmd)
                    self.main_ctrl.send_cmd(new_cmd, self)

                    handler.send_text("ok %.4f %.4f %.4f" % (data[0], data[1],
                                                            data[2]))
            except ValueError as e:
                handler.send_text("error %s" % e.args[0])

            except Exception:
                logger.exception("Unhandle Error")
                handler.send_text("error UNKNOW_ERROR")
                self.stack.exit_task(self)

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
        handler.send_text("continue")

    @check_mainboard
    def do_h_correction(self, handler, h=None):
        if h is not None:
            corr_cmd = do_h_correction(h=h)
            self.main_ctrl.send_cmd(corr_cmd, self)
            handler.send_text("continue")
            handler.send_text("ok 0")
            return

        def stage_test_h(msg):
            try:
                if msg.startswith("Bed Z-Height at"):
                    self._mainboard_msg_filter = None
                    self._busy = False

                    data = float(msg.rsplit(" ", 1)[-1])
                    handler.send_text("DEBUG H: %.4f" % data)

                    corr_cmd = do_h_correction(delta=data)
                    self.main_ctrl.send_cmd(corr_cmd, self)

                    handler.send_text("ok %.4f" % data)
            except ValueError as e:
                handler.send_text("error %s" % e.args[0])

            except Exception:
                logger.exception("Unhandle Error")
                handler.send_text("error UNKNOW_ERROR")
                self.stack.exit_task(self)

        self._busy = True
        self._mainboard_msg_filter = stage_test_h
        self.main_ctrl.send_cmd("G30X0Y0", self)
        handler.send_text("continue")

    def on_timer(self, watcher, revent):
        try:
            self.main_ctrl.patrol(self)
        except SystemError:
            self.stack.exit_task(self)
