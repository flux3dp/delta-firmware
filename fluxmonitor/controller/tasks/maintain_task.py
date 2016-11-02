
from json import dumps
import logging

from fluxmonitor.player.main_controller import MainController
from fluxmonitor.player.head_controller import (HeadController,
                                                HeadError,
                                                HeadOfflineError,
                                                HeadResetError,
                                                HeadTypeError)
from fluxmonitor.player.options import Options
from fluxmonitor.hal.tools import reset_mb
from fluxmonitor.err_codes import (EXEC_HEAD_ERROR,
                                   RESOURCE_BUSY,
                                   SUBSYSTEM_ERROR,
                                   TOO_LARGE,
                                   UNKNOWN_COMMAND)
from fluxmonitor.storage import Metadata
from fluxmonitor.player import macro

from .base import (CommandMixIn,
                   DeviceOperationMixIn,
                   DeviceMessageReceiverMixIn)
from .update_hbfw_task import UpdateHbFwTask

logger = logging.getLogger(__name__)


class MaintainTask(DeviceOperationMixIn, DeviceMessageReceiverMixIn,
                   CommandMixIn):
    st_id = -1
    main_ctrl = None
    head_ctrl = None

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
        self.head_ctrl.bootstrap(self)

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
        except (HeadOfflineError, HeadResetError) as e:
            logger.debug("Head reset")
            self.head_ctrl.bootstrap(self)
            if self._macro:
                self._on_macro_error(e)

        except HeadError as e:
            logger.info("Head Error: %s", e)

        except SystemError as e:
            logger.exception("Unhandle Error")
            if self._macro:
                self._on_macro_error(e)

        except Exception:
            logger.exception("Unhandle Error")

    def dispatch_cmd(self, handler, cmd, *args):
        if cmd == "stop_load_filament":
            self.send_mainboard("@HOME_BUTTON_TRIGGER\n")
            return
        elif self._busy:
            raise RuntimeError(RESOURCE_BUSY)

        if cmd == "home":
            self.do_home(handler)

        elif cmd == "calibration" or cmd == "calibrate":
            try:
                threshold = float(args[0])
                if threshold < 0.01:
                    threshold = 0.01
            except (ValueError, IndexError):
                threshold = float("inf")

            clean = "clean" in args
            self.do_calibrate(handler, threshold, clean=clean)

        elif cmd == "zprobe":
            if len(args) > 0:
                h = float(args[0])
                self.do_h_correction(handler, h=h)
            else:
                self.do_h_correction(handler)

        elif cmd == "load_filament":
            self.do_load_filament(handler, int(args[0]), float(args[1]))

        elif cmd == "unload_filament":
            self.do_unload_filament(handler, int(args[0]), float(args[1]))

        elif cmd == "headinfo":
            self.head_info(handler)

        elif cmd == "headstatus":
            self.head_status(handler)

        elif cmd == "reset_mb":
            reset_mb()
            self.stack.exit_task(self)
            handler.send_text("ok")

        elif cmd == "extruder_temp":
            self.do_change_extruder_temperature(handler, *args)

        elif cmd == "x78":
            self.do_x78(handler)

        elif cmd == "update_head":
            self.update_toolhead_fw(handler, *args)

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOWN_COMMAND)

    def do_x78(self, handler):
        dataset = []

        def on_message_cb(msg):
            if not msg.startswith("LN "):
                dataset.append(msg)

        def on_success_cb():
            handler.send_text("\n".join(dataset))
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            handler.send_text("error %s" % " ".join(error.args))
            self._busy = False

        self._macro = macro.CommandMacro(on_success_cb, ["X78"], on_message_cb)
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)

    def do_change_extruder_temperature(self, handler, sindex, stemp):
        if not self.head_ctrl.ready:
            raise HeadError(EXEC_HEAD_ERROR, RESOURCE_BUSY)
        module = self.head_ctrl.status()["module"]
        if module != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", module)

        self.head_ctrl.send_cmd("H%i%.1f" % (int(sindex), float(stemp)), self)
        handler.send_text("ok")

    def do_load_filament(self, handler, index, temp):
        if not self.head_ctrl.ready:
            raise HeadError(EXEC_HEAD_ERROR, RESOURCE_BUSY)
        module = self.head_ctrl.status()["module"]
        if module != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", module)

        def on_load_done():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_heating_done():
            def on_message(msg):
                try:
                    if msg == "CTRL FILAMENT+":
                        handler.send_text("CTRL LOADING")
                    elif msg == "CTRL FILAMENT-":
                        handler.send_text("CTRL WAITING")
                except Exception:
                    self.send_mainboard("@HOME_BUTTON_TRIGGER\n")
                    raise

            opt = Options(head="EXTRUDER")
            cmds = (("T%i" % index),
                    ("C3" if opt.filament_detect == "N" else "C3+"))
            self._macro = macro.CommandMacro(on_load_done, cmds,
                                             on_message_cb=on_message)
            self._macro.start(self)

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            if isinstance(self._macro, macro.WaitHeadMacro):
                rt = self.head_ctrl.status().get("rt")
                if rt:
                    try:
                        handler.send_text("CTRL HEATING %.1f" % rt[index])
                    except IndexError:
                        pass

        self._macro = macro.WaitHeadMacro(on_heating_done,
                                          "H%i%.1f" % (index, temp))
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_unload_filament(self, handler, index, temp):
        if not self.head_ctrl.ready:
            raise HeadError(EXEC_HEAD_ERROR, RESOURCE_BUSY)
        module = self.head_ctrl.status()["module"]
        if module != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", module)

        def on_load_done():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_heating_done():
            self._macro = macro.CommandMacro(on_load_done, ("T%i" % index,
                                                            "C4", ))
            self._macro.start(self)

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            if isinstance(self._macro, macro.WaitHeadMacro):
                st = self.head_ctrl.status()
                handler.send_text("CTRL HEATING %.1f" % st.get("rt")[index])
            else:
                handler.send_text("CTRL UNLOADING")

        self._macro = macro.WaitHeadMacro(on_heating_done,
                                          "H%i%.1f" % (index, temp))
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)
        handler.send_text("continue")

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

        self._macro = macro.CommandMacro(on_success_cb, ["G28+"])
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)

    def do_calibrate(self, handler, threshold, clean=False):
        def on_success_cb():
            while self._macro.debug_logs:
                handler.send_text("DEBUG " + self._macro.debug_logs.popleft())

            p1, p2, p3 = self._macro.history[-1]
            handler.send_text("ok %.4f %.4f %.4f" % (p1, p2, p3))
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            while self._macro.debug_logs:
                handler.send_text("DEBUG " + self._macro.debug_logs.popleft())
            handler.send_text("CTRL POINT %i" % len(self._macro.data))

        correct_at_final = True if threshold == float("inf") else False
        self._macro = macro.CorrectionMacro(on_success_cb, clean=clean,
                                            threshold=threshold,
                                            correct_at_final=correct_at_final)
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_h_correction(self, handler, h=None):
        if h is not None:
            if h > 245 or h < 238:
                logger.error("H ERROR: %f" % h)
                raise ValueError("INPUT_FAILED")

            cm = Metadata()
            cm.plate_correction = {"H": h}
            self.main_ctrl.send_cmd("M666H%.4f" % h, self)
            handler.send_text("continue")
            handler.send_text("ok 0")
            return

        def on_success_cb():
            while self._macro.debug_logs:
                handler.send_text("DEBUG " + self._macro.debug_logs.popleft())
            handler.send_text("ok %.4f" % self._macro.history[0])
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False

        def on_macro_error(error):
            self._macro.giveup()
            self._macro = self._on_macro_error = self._on_macro_running = None
            self._busy = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            handler.send_text("CTRL ZPROBE")

        self._macro = macro.ZprobeMacro(on_success_cb, threshold=float("inf"),
                                        clean=False)
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self._busy = True
        self._macro.start(self)
        handler.send_text("continue")

    def head_info(self, handler):
        dataset = self.head_ctrl.info().copy()
        dataset["version"] = dataset.get("VERSION")
        dataset["module"] = dataset.get("TYPE")
        handler.send_text("ok " + dumps(dataset))

    def head_status(self, handler):
        handler.send_text("ok " + dumps(self.head_ctrl.status()))

    def update_toolhead_fw(self, handler, mimetype, sfilesize):
        def ret_callback(success):
            logger.debug("Toolhead update retuen: %s", success)
            self.timer_watcher.start()

        filesize = int(sfilesize)
        if filesize > (1024 * 256):
            raise RuntimeError(TOO_LARGE)

        t = UpdateHbFwTask(self.stack, handler, filesize)
        self.stack.enter_task(t, ret_callback)
        handler.send_text("continue")
        self.timer_watcher.stop()

    def on_timer(self, watcher, revent):
        self.meta.update_device_status(self.st_id, 0, "N/A",
                                       self.handler.address)

        try:
            self.main_ctrl.patrol(self)
            self.head_ctrl.patrol(self)
            if self._on_macro_running:
                self._on_macro_running()

        except (HeadOfflineError, HeadResetError) as e:
            logger.info("%s", e)
            if self._macro:
                self.on_macro_error(e)
            self.head_ctrl.bootstrap(self)

        except RuntimeError as e:
            logger.info("%s", e)
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

        except IOError:
            logger.warn("Socket IO Error")
            self.handler.close()

        except Exception:
            logger.exception("Unhandle error")
            self.handler.close()

    def clean(self):
        self.send_mainboard("@HOME_BUTTON_TRIGGER\n")

        if self.timer_watcher:
            self.timer_watcher.stop()
            self.timer_watcher = None

        try:
            if self.main_ctrl:
                self.main_ctrl.close(self)
                self.main_ctrl = None
        except Exception:
            logger.exception("Mainboard error while quit")

        try:
            if self.head_ctrl:
                self.head_ctrl.close(self)
                self.head_ctrl = None
        except Exception:
            logger.exception("Toolhead error while quit")

        self.meta.update_device_status(0, 0, "N/A", "")
