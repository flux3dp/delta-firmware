
import logging
import socket
import re

from fluxmonitor.player.main_controller import MainController
from fluxmonitor.player.head_controller import HeadController
from fluxmonitor.player import macro
from fluxmonitor.storage import Metadata
from fluxmonitor.misc import correction
from fluxmonitor.config import uart_config

from fluxmonitor.err_codes import RESOURCE_BUSY, UNKNOWN_COMMAND, \
    SUBSYSTEM_ERROR

from .base import CommandMixIn, DeviceOperationMixIn, \
    DeviceMessageReceiverMixIn

RE_REPORT_DIST = re.compile("X:(?P<X>(-)?[\d]+(.[\d]+)?) "
                            "Y:(?P<Y>(-)?[\d]+(.[\d]+)?) "
                            "Z:(?P<Z>(-)?[\d]+(.[\d]+)?) ")
logger = logging.getLogger(__name__)


class MaintainTask(DeviceOperationMixIn, DeviceMessageReceiverMixIn,
                   CommandMixIn):
    st_id = -1

    def __init__(self, stack, handler):
        super(MaintainTask, self).__init__(stack, handler)
        self.meta = Metadata()

        self._ready = 0
        self._busy = False

        self._macro = None
        self._on_macro_error = None
        self._on_macro_running = None

        def on_mainboard_ready(_):
            self._ready |= 1
            handler.send_text("ok")

        self.main_ctrl = MainController(executor=self, bufsize=14,
                                        ready_callback=on_mainboard_ready)
        self.head_ctrl = HeadController(executor=self, error_level=0,
                                        ready_callback=lambda _: None)

        def on_mainboard_empty(sender):
            if self._macro:
                self._macro.on_command_empty(self)

        def on_mainboard_sendable(sender):
            if self._macro:
                self._macro.on_command_sendable(self)

        self.main_ctrl.callback_msg_empty = on_mainboard_empty
        self.main_ctrl.callback_msg_sendable = on_mainboard_sendable

        self.timer_watcher = stack.loop.timer(1, 1, self.on_timer)
        self.timer_watcher.start()

    def on_exit(self):
        self.close()
        super(MaintainTask, self).on_exit()

    def send_mainboard(self, msg):
        if self._uart_mb.send(msg) != len(msg):
            raise Exception("DIE")

    def send_headboard(self, msg):
        self._uart_hb.send(msg)

    def on_mainboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(1024)
            if not buf:
                logger.error("Mainboard connection broken")
                self.stack.exit_task(self)

            for msg in self.recv_from_mainboard(buf):
                if self._macro:
                    self._macro.on_mainboard_message(msg, self)
                self.main_ctrl.on_message(msg, self)
        except (RuntimeError, SystemError) as e:
            if self._macro:
                self._on_macro_error(e)
        except Exception:
            logger.exception("Unhandle Error")

    def on_headboard_message(self, watcher, revent):
        try:
            buf = watcher.data.recv(1024)
            if not buf:
                logger.error("Headboard connection broken")
                self.stack.exit_task(self)

            for msg in self.recv_from_headboard(buf):
                if self._macro:
                    self._macro.on_headboard_message(msg, self)
                self.head_ctrl.on_message(msg, self)
        except (RuntimeError, SystemError) as e:
            if self._macro:
                self._on_macro_error(e)
        except Exception:
            logger.exception("Unhandle Error")

    def dispatch_cmd(self, handler, cmd, *args):
        if self._busy:
            raise RuntimeError(RESOURCE_BUSY)

        if cmd == "home":
            self.do_home(handler)

        elif cmd == "calibration":
            clean = "clean" in args
            self.do_calibration(handler, clean=clean)

        elif cmd == "cor_h":
            if len(args) > 0:
                h = float(args[0])
                self.do_h_correction(handler, h=h)
            else:
                self.do_h_correction(handler)

        elif cmd == "reset_mb":
            s = socket.socket(socket.AF_UNIX)
            s.connect(uart_config["control"])
            s.send(b"reset mb")
            s.close()
            self.stack.exit_task(self)
            handler.send_text("ok")

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOWN_COMMAND)

    def load_filament(self, index, temp):
        pass
        # def head_ready(self, _):
        #     self.head_ctrl.sender
        #
        # self.head_ctrl = HeadController(
        #     executor=self, ready_callback=head_ready,
        #     required_module="EXTRUDER", error_level=0)

    def unload_filament(self):
        pass

    def do_home(self, handler):
        def on_success_cb():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            handler.send_text("error %s" % " ".join(error.args))
            self._busy = False

        def on_macro_running():
            handler.send_text("DEBUG: HOME")

        self._macro = macro.CommandMacro(on_success_cb, ["G28+"])
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._busy = True
        self._macro.start(self)

    def do_calibration(self, handler, clean=False):
        def on_success_cb():
            p1, p2, p3 = self._macro.history[0]
            handler.send_text("ok %.4f %.4f %.4f" % (p1, p2, p3))
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            handler.send_text("DEBUG: Point:%i/3" % len(self._macro.data))

        self._macro = macro.CorrectionMacro(on_success_cb, clean=clean,
                                            threshold=float("inf"))
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_h_correction(self, handler, h=None):
        if h is not None:
            if h > 248 or h < 230:
                logger.error("H ERROR: %f" % h)
                raise ValueError("INPUT_FAILED")

            cm = Metadata()
            cm.plate_correction = {"H": h}
            self.main_ctrl.send_cmd("M666H%.4f" % h, self)
            handler.send_text("continue")
            handler.send_text("ok 0")
            return

        def on_success_cb():
            handler.send_text("ok %.4f" % self._macro.history[0])
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            handler.send_text("DEBUG: DA~DA~DA~")

        self._macro = macro.ZprobeMacro(on_success_cb, threshold=float("inf"),
                                        clean=False)
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)
        handler.send_text("continue")
        # if h is not None:
        #     corr_cmd = do_h_correction(h=h)
        #     self.main_ctrl.send_cmd(corr_cmd, self)
        #     handler.send_text("continue")
        #     handler.send_text("ok 0")
        #     return
        #
        # def stage_test_h(msg):
        #     try:
        #         if msg.startswith("Bed Z-Height at"):
        #             self._mainboard_msg_filter = None
        #             self._busy = False
        #
        #             data = float(msg.rsplit(" ", 1)[-1])
        #             handler.send_text("DEBUG H: %.4f" % data)
        #
        #             corr_cmd = do_h_correction(delta=data)
        #             self.main_ctrl.send_cmd(corr_cmd, self)
        #
        #             handler.send_text("ok %.4f" % data)
        #     except ValueError as e:
        #         handler.send_text("error %s" % e.args[0])
        #
        #     except Exception:
        #         logger.exception("Unhandle Error")
        #         handler.send_text("error UNKNOWN_ERROR")
        #         self.stack.exit_task(self)
        #
        # self._busy = True
        # self._mainboard_msg_filter = stage_test_h
        # self.main_ctrl.send_cmd("G30X0Y0", self)
        # handler.send_text("continue")

    def on_timer(self, watcher, revent):
        self.meta.update_device_status(self.st_id, 0, "N/A", "")

        try:
            self.main_ctrl.patrol(self)
            self.head_ctrl.patrol(self)
            if self._on_macro_running:
                self._on_macro_running()

        except RuntimeError as e:
            if self._macro:
                self.on_macro_error(e)

        except SystemError:
            if self._ready:
                logger.exception("Mainboard dead during maintain")
                self.handler.send_text("error %s" % SUBSYSTEM_ERROR)
                self.handler.close()
            else:
                self.handler.send_text("error %s" % SUBSYSTEM_ERROR)
                self.stack.exit_task(self)

        except socket.error:
            logger.warn("Socket IO Error")
            self.handler.close()

        except Exception:
            logger.exception("Unhandle error")
            self.handler.close()

    def close(self):
        if self.timer_watcher:
            self.timer_watcher.stop()
            self.timer_watcher = None
        if self.main_ctrl:
            self.main_ctrl.close(self)
            self.main_ctrl = None
        self.meta.update_device_status(0, 0, "N/A", "")

