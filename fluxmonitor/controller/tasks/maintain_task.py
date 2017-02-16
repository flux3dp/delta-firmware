
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
from fluxmonitor.storage import Preference, metadata
from fluxmonitor.player import macro
from fluxmonitor.hal import tools

from .base import (CommandMixIn,
                   DeviceOperationMixIn)
from .update_hbfw_task import UpdateHbFwTask

logger = logging.getLogger(__name__)


class MaintainTask(DeviceOperationMixIn, CommandMixIn):
    st_id = -1
    mainboard = None
    toolhead = None
    busying = False
    toolhead_updating = False

    def __init__(self, stack, handler):
        super(MaintainTask, self).__init__(stack, handler)

        self.busying = False

        self._macro = None
        self._on_macro_error = None
        self._on_macro_running = None

        def on_mainboard_ready(_):
            self.busying = False
            handler.send_text("ok")

        def on_mainboard_empty(sender):
            if self._macro:
                self._macro.on_command_empty(self)

        def on_mainboard_sendable(sender):
            if self._macro:
                self._macro.on_command_sendable(self)

        def on_mainboard_ctrl(sender, data):
            if self._macro:
                self._macro.on_ctrl_message(self, data)

        self.mainboard = MainController(
            self._sock_mb.fileno(), bufsize=14,
            empty_callback=on_mainboard_empty,
            sendable_callback=on_mainboard_sendable,
            ctrl_callback=on_mainboard_ctrl)
        self.toolhead = HeadController(self._sock_th.fileno())

        self.mainboard.bootstrap(on_mainboard_ready)
        self.toolhead.bootstrap(self.on_toolhead_ready)

    def on_toolhead_ready(self, sender):
        if sender.module_name and sender.module_name != "N/A":
            tools.toolhead_on()

    def on_mainboard_message(self, watcher, revent):
        try:
            self.mainboard.handle_recv()

        except IOError:
            logger.error("Mainboard connection broken")
            if self.busying:
                self.handler.send_text("error SUBSYSTEM_ERROR")
            self.stack.exit_task(self)
        except (RuntimeError, SystemError) as e:
            if self._macro:
                self._on_macro_error(e)
        except Exception:
            logger.exception("Unhandle Error")

    def on_headboard_message(self, watcher, revent):
        try:
            self.toolhead.handle_recv()
        except IOError:
            logger.error("Toolhead connection broken")
            self.stack.exit_task(self)

        except (HeadOfflineError, HeadResetError) as e:
            logger.debug("Head reset")
            tools.toolhead_standby()
            self.toolhead.bootstrap(self.on_toolhead_ready)
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
            self.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n", raw=1)
            return
        elif self.busying:
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

        elif cmd == "diagnosis_sensor":
            self.diagnosis_sensor(handler)

        elif cmd == "update_head":
            self.update_toolhead_fw(handler, *args)

        elif cmd == "hal_diagnosis":
            handler.send_text("ok " + tools.hal_diagnosis())

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOWN_COMMAND)

    def diagnosis_sensor(self, handler):
        dataset = []

        def on_message_cb(msg):
            if msg.startswith("DATA "):
                kv = msg[5:].split(" ", 1)
                if len(kv) == 2:
                    dataset.append("%s=%s" % (kv[0], kv[1]))
                else:
                    dataset.append(kv)

        def on_success_cb():
            handler.send_text("ok " + "\x00".join(dataset))
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            handler.send_text("error %s" % " ".join(error.args))
            self.busying = False

        self._macro = macro.CommandMacro(on_success_cb, ["M666L1"],
                                         on_message_cb)
        self._on_macro_error = on_macro_error
        self.busying = True
        self._macro.start(self)

    def do_change_extruder_temperature(self, handler, sindex, stemp):
        if not self.toolhead.ready or not self.toolhead.sendable():
            raise HeadError(EXEC_HEAD_ERROR, RESOURCE_BUSY)
        module = self.toolhead.status["module"]
        if module != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", module)

        self.toolhead.ext.set_heater(int(sindex), float(stemp))
        handler.send_text("ok")

    def do_load_filament(self, handler, index, temp):
        if not self.toolhead.ready or not self.toolhead.sendable():
            raise HeadError(EXEC_HEAD_ERROR, RESOURCE_BUSY)
        module = self.toolhead.status["module"]
        if module != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", module)

        def on_load_done():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_heating_done():
            def on_message(msg):
                try:
                    if msg == "FILAMENT+":
                        handler.send_text("CTRL LOADING")
                    elif msg == "FILAMENT-":
                        handler.send_text("CTRL WAITING")
                except Exception:
                    self.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n")
                    raise

            opt = Options(head="EXTRUDER")
            self._macro = macro.LoadFilamentMacro(on_load_done, index,
                                                  opt.filament_detect != "N",
                                                  on_message)
            self._macro.start(self)

        def on_macro_running():
            if isinstance(self._macro, macro.ControlHeaterMacro):
                rt = self.toolhead.status.get("rt")
                if rt:
                    try:
                        handler.send_text("CTRL HEATING %.1f" % rt[index])
                    except IndexError:
                        pass

        self._macro = macro.ControlHeaterMacro(on_heating_done, index, temp)
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self.busying = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_unload_filament(self, handler, index, temp):
        if not self.toolhead.ready:
            raise HeadError(EXEC_HEAD_ERROR, RESOURCE_BUSY)
        module = self.toolhead.status["module"]
        if module != "EXTRUDER":
            raise HeadTypeError("EXTRUDER", module)

        def on_load_done():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_heating_done():
            self._macro = macro.UnloadFilamentMacro(on_load_done, index)
            self._macro.start(self)

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            if isinstance(self._macro, macro.WaitHeadMacro):
                st = self.toolhead.status.copy()
                handler.send_text("CTRL HEATING %.1f" % st.get("rt")[index])
            else:
                handler.send_text("CTRL UNLOADING")

        self._macro = macro.ControlHeaterMacro(on_heating_done, index, temp)
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self.busying = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_home(self, handler):
        def on_success_cb():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            handler.send_text("error %s" % " ".join(error.args))
            self.busying = False

        self._macro = macro.CommandMacro(on_success_cb, ["G28+"])
        self._on_macro_error = on_macro_error
        self.busying = True
        self._macro.start(self)

    def do_calibrate(self, handler, threshold, clean=False):
        def on_success_cb():
            while self._macro.debug_logs:
                handler.send_text("DEBUG " + self._macro.debug_logs.popleft())

            p1, p2, p3 = self._macro.history[-1]
            handler.send_text("ok %.4f %.4f %.4f" % (p1, p2, p3))
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False
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
        self.busying = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_h_correction(self, handler, h=None):
        if h is not None:
            if h > 245 or h < 238:
                logger.error("H ERROR: %f" % h)
                raise ValueError("INPUT_FAILED")

            Preference.instance().plate_correction = {"H": h}
            self.mainboard.send_cmd("M666H%.4f" % h, self)
            handler.send_text("continue")
            handler.send_text("ok 0")
            return

        def on_success_cb():
            while self._macro.debug_logs:
                handler.send_text("DEBUG " + self._macro.debug_logs.popleft())
            handler.send_text("ok %.4f" % self._macro.history[0])
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False
            handler.send_text("error %s" % " ".join(error.args))

        def on_macro_running():
            handler.send_text("CTRL ZPROBE")

        self._macro = macro.ZprobeMacro(on_success_cb, threshold=float("inf"),
                                        clean=False)
        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self.busying = True
        self._macro.start(self)
        handler.send_text("continue")

    def head_info(self, handler):
        dataset = self.toolhead.profile.copy()
        dataset["version"] = dataset.get("VERSION")
        dataset["module"] = dataset.get("TYPE")
        handler.send_text("ok " + dumps(dataset))

    def head_status(self, handler):
        handler.send_text("ok " + dumps(self.toolhead.status))

    def update_toolhead_fw(self, handler, mimetype, sfilesize):
        def ret_callback(success):
            logger.debug("Toolhead update retuen: %s", success)
            self.toolhead_updating = False

        filesize = int(sfilesize)
        if filesize > (1024 * 256):
            raise RuntimeError(TOO_LARGE)

        t = UpdateHbFwTask(self.stack, handler, filesize)
        self.stack.enter_task(t, ret_callback)
        handler.send_text("continue")
        self.toolhead_updating = True

    def on_timer(self, watcher, revent):
        metadata.update_device_status(self.st_id, 0, "N/A",
                                      self.handler.address)

        if self.toolhead_updating:
            return

        try:
            self.mainboard.patrol()
            self.toolhead.patrol()

            if self._on_macro_running:
                self._on_macro_running()

        except (HeadOfflineError, HeadResetError) as e:
            logger.info("%s", e)
            tools.toolhead_standby()
            if self._macro:
                self.on_macro_error(e)
            self.toolhead.bootstrap(self.on_toolhead_ready)

        except RuntimeError as e:
            logger.info("%s", e)
            if self._macro:
                self.on_macro_error(e)

        except SystemError:
            if self.busying:
                self.handler.send_text("error %s" % SUBSYSTEM_ERROR)
                self.stack.exit_task(self)
            else:
                logger.exception("Mainboard dead during maintain")
                self.handler.send_text("error %s" % SUBSYSTEM_ERROR)
                self.handler.close()

        except IOError:
            logger.warn("Socket IO Error")
            self.handler.close()

        except Exception:
            logger.exception("Unhandle error")
            self.handler.close()

    def clean(self):
        try:
            if self.mainboard:
                self.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n", raw=1)
                self.mainboard.close()
                self.mainboard = None
        except Exception:
            logger.exception("Mainboard error while quit")

        try:
            if self.toolhead:
                if self.toolhead.ready:
                    # > Check should toolhead power deplayoff
                    if self.toolhead.module_name == "EXTRUDER":
                        for t in self.toolhead.status.get("rt", ()):
                            if t > 60:
                                logger.debug("Set toolhead delay off")
                                metadata.delay_toolhead_poweroff = b"\x01"
                                break
                    # ^
                    self.toolhead.shutdown()
                self.toolhead = None
        except Exception:
            logger.exception("Toolhead error while quit")

        try:
            tools.toolhead_standby()
        except Exception:
            logger.exception("HAL control error while quit")

        metadata.update_device_status(0, 0, "N/A", "")
