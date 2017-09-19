
from pyev import EV_READ
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
from fluxmonitor.config import MAINTAIN_MOVEMENT_PARAMS as MOVE_COMMAND
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
    _has_zprobe = False

    def __init__(self, stack, handler):
        super(MaintainTask, self).__init__(stack, handler)

        self.busying = False
        self._has_zprobe = False

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

        except IOError as e:
            from errno import EAGAIN
            if e.errno == EAGAIN:
                # TODO: There is a recv bug in C code, this is a quit fix to
                # passthrough it.
                return
            logger.exception("Mainboard connection broken")
            if self.mainboard.ready:
                self.handler.send_text("error SUBSYSTEM_ERROR")
                self.handler.close()
            else:
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
            logger.exception("Toolhead connection broken")
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

        elif cmd == "move":
            try:
                opt = {k: float(v) for k, v in (arg.split(':', 1) for arg in args)}
                self.do_move(handler, **opt)
            except (ValueError, IndexError):
                raise RuntimeError(UNKNOWN_COMMAND)

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
                self.do_zprobe(handler, h=h)
            else:
                self.do_zprobe(handler)

        elif cmd == "load_filament":
            self.do_load_filament(handler, int(args[0]), float(args[1]))

        elif cmd == "load_flexible_filament":
            self.do_load_filament(handler, int(args[0]), float(args[1]), True)

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
            self.do_hal_diagnosis(handler)

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

    def do_move(self, handler, **kw):
        def on_success_cb():
            handler.send_text("ok")
            self._macro = self._on_macro_error = self._on_macro_running = None
            self.busying = False

        def on_macro_error(error):
            self._macro.giveup(self)
            self._macro = self._on_macro_error = self._on_macro_running = None
            handler.send_text("error %s" % " ".join(error.args))
            self.busying = False

        subcmd = ''.join(MOVE_COMMAND[k] % v for k, v in kw.items() if k in MOVE_COMMAND)
        if 'E' in subcmd:
            cmds = ['T2', 'G92E0', 'G1' + subcmd, 'T0']
        else:
            cmds = ['G1' + subcmd]

        self._macro = macro.CommandMacro(on_success_cb, cmds)
        self._on_macro_error = on_macro_error
        self._macro.start(self)
        self.busying = True

    def do_load_filament(self, handler, index, temp, disable_accelerate=False):
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
            if opt.plus_extrusion:
                self.mainboard.send_cmd("M92E145")
            self._macro = macro.LoadFilamentMacro(on_load_done, index,
                                                  opt.filament_detect,
                                                  disable_accelerate,
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

        cor = Preference.instance().plate_correction
        self._macro = macro.CommandMacro(on_success_cb, [
            "M666X%(X).4fY%(Y).4fZ%(Z).4fR%(R).4fD%(D).5fH%(H).4f" % cor,
            "G28+"])
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

        opt = Options(head="EXTRUDER")

        correct_at_final = True if threshold == float("inf") else False

        if self._has_zprobe is False:
            self._has_zprobe = True
            opt = Options(head="EXTRUDER")
            self._macro = macro.CorrectionMacro(
                on_success_cb, threshold=threshold, clean=clean,
                dist=opt.zprobe_dist, correct_at_final=correct_at_final)
        else:
            self._macro = macro.CorrectionMacro(
                on_success_cb, threshold=threshold, clean=clean,
                correct_at_final=correct_at_final)

        self._on_macro_error = on_macro_error
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self.busying = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_zprobe(self, handler, h=None):
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

        if self._has_zprobe is False:
            self._has_zprobe = True
            opt = Options(head="EXTRUDER")
            self._macro = macro.ZprobeMacro(
                on_success_cb, threshold=float("inf"), dist=opt.zprobe_dist)
        else:
            self._macro = macro.ZprobeMacro(
                on_success_cb, threshold=float("inf"))
        self._on_macro_running = on_macro_running
        self._on_macro_error = on_macro_error
        self.busying = True
        self._macro.start(self)
        handler.send_text("continue")

    def do_hal_diagnosis(self, handler):
        memory_stack = []

        def on_resp(ret, data):
            try:
                io_w, timer_w, sock = data
                io_w.stop()
                timer_w.stop()
                sock.close()
            finally:
                handler.send_text("ok %s" % ret)
                self.busying = False
                while memory_stack:
                    memory_stack.pop()

        def on_io(watcher, revent):
            ret = tools.hal_diagnosis_result(watcher.data[-1])
            on_resp(ret, watcher.data)

        def on_timeout(watcher, revent):
            on_resp("HAL_TIMEOUT", watcher.data)

        try:
            sock = tools.begin_hal_diagnosis()
            self.busying = True

            io_watcher = self.stack.loop.io(sock, EV_READ, on_io)
            t_watcher = self.stack.loop.timer(90, 0, on_timeout)
            memory_stack.append(io_watcher)
            memory_stack.append(t_watcher)
            memory_stack.append(sock)

            io_watcher.data = t_watcher.data = (io_watcher, t_watcher, sock)
            io_watcher.start()
            t_watcher.start()
        except Exception:
            logger.exception("HAL diagnosis error")
            handler.send_text("error SUBSYSTEM_ERROR")

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
                self._on_macro_error(e)
            self.toolhead.bootstrap(self.on_toolhead_ready)

        except RuntimeError as e:
            logger.info("%s", e)
            if self._macro:
                self._on_macro_error(e)

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
