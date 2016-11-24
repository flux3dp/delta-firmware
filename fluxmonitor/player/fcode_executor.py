
from collections import deque
import logging

from fluxmonitor.diagnosis.god_mode import allow_god_mode
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.err_codes import (UNKNOWN_ERROR, EXEC_BAD_COMMAND,
                                   SUBSYSTEM_ERROR)
from fluxmonitor.hal.tools import reset_hb

from .base import BaseExecutor
from .base import (
    ST_STARTING, ST_RUNNING, ST_COMPLETED, ST_COMPLETING)

from ._device_fsm import PyDeviceFSM
from .macro import (StartupMacro, WaitHeadMacro, CorrectionMacro, ZprobeMacro,
                    ControlHeaterMacro, ControlToolheadMacro)

from .main_controller import MainController
from .head_controller import (HeadController, check_toolhead_errno,
                              exec_command as exec_toolhead_cmd)

logger = logging.getLogger(__name__)


class AutoResume(object):
    __resume_counter = 0
    __resume_timestamp = 0

    def __is_usbc_cable_issue(self):
        if self.options.autoresume and self.error_symbol and \
                'HEAD_ERROR' in self.error_symbol.args:
            if "HEAD_OFFLINE" in self.error_symbol.args:
                return True
            if "RESET" in self.error_symbol.args:
                return True
        return False

    def paused(self):
        super(AutoResume, self).paused()
        if self.status_id & 192:
            # Game over
            return
        else:
            if self.__is_usbc_cable_issue() is False:
                return

            if self.status_id & ST_STARTING == ST_STARTING:
                # Do not do autoresume during starting up
                return

            if self.__resume_timestamp + 180 > time():
                self.__resume_counter = 1
            else:
                self.__resume_timestamp = time()
                self.__resume_counter += 1

            # if self.__resume_counter > 3:
            if False:
                logger.error("Autoresume invalied because error occour more "
                             "then 3 times.")
            else:
                logger.error("Autoresume activated")
                self.resume()


class FcodeExecutor(AutoResume, BaseExecutor):
    mainboard = None
    toolhead = None
    macro = None
    paused_macro = None
    th_error_flag = 0xfffff

    # Subprocess to read contents
    _task_loader = None
    # Input is finished
    _eof = False
    # Gcode parser
    _fsm = None
    _mb_stashed = False
    _cmd_queue = None

    def __init__(self, mainboard_io, headboard_io, task_loader, options):
        super(FcodeExecutor, self).__init__(mainboard_io, headboard_io)
        self._task_loader = task_loader
        self.options = options
        self._padding_bufsize = max(options.play_bufsize * 2, 64)

        self.mainboard = MainController(
            sock_fd=self._mbsock.fileno(), bufsize=options.play_bufsize,
            empty_callback=self._on_mb_empty,
            sendable_callback=self._on_mb_sendable,
            ctrl_callback=self._on_mb_ctrl)

        self.mainboard.bootstrap(self._on_mainboard_ready)

        self.toolhead = HeadController(sock_fd=self._thsock.fileno(),
                                       required_module=options.head)

        self.th_error_flag = self.options.head_error_level
        self._fsm = PyDeviceFSM(max_x=self.options.max_x,
                                max_y=self.options.max_y,
                                max_z=self.options.max_z)

        try:
            task_loader.validate_status()
            self.start()

        except Exception as e:
            self.abort(e)

    @property
    def traveled(self):
        return self._fsm.get_traveled()

    @property
    def position(self):
        return self._fsm.get_position()

    def get_status(self):
        st = self.toolhead.status
        st.update(super(FcodeExecutor, self).get_status())
        return st

    def _on_mainboard_ready(self, mainboard):
        # status_id should be (4, 6, 18)
        self.toolhead.bootstrap(self._on_toolhead_ready)

    def _on_toolhead_ready(self, toolhead):
        # status_id should be (4, 6, 18)
        # Mainboard should be ready
        def callback(toolhead):
            if self.toolhead.allset:
                self._on_toolhead_recovered_and_allset(self.toolhead)
            else:
                m = WaitHeadMacro(self._on_toolhead_recovered_and_allset)
                m.start(self)

        if self.status_id & ST_RUNNING:
            self.toolhead.recover(callback)
        else:
            self._on_toolhead_recovered_and_allset(self.toolhead)

    def _on_toolhead_recovered_and_allset(self, *args):
        # status_id should be (4, 6, 18)
        # Mainboard should be ready
        # Toolhead should be ready
        # Toolhead status should be allset
        if self.status_id == 4 or self.status_id == 6:
            self.started()
        elif self.status_id == 18:
            if self._mb_stashed:
                self.mainboard.send_cmd("C2F")
                self._mb_stashed = False
            else:
                self.resumed()
                if self.macro:
                    self.macro.start(self)
                else:
                    self.fire()
        else:
            logger.error("Unknown action for status %i in "
                         "on_toolhead_recovered_and_allset", self.status_id)

    def _clear_macro(self):
        self.macro = None
        self.fire()

    def started(self):
        super(FcodeExecutor, self).started()

        def callback():
            logging.debug("StartupMacro completed.")
            self.macro = None
            self._cmd_queue = deque()
            self._fsm.set_max_exec_time(0.1)
            if self.options.correction in ("A", "H"):
                self.do_correction()
            else:
                self.fire()

        self.macro = StartupMacro(callback, self.options)
        logging.debug("StartupMacro start.")
        self.macro.start(self)

    def do_correction(self):
        def correction_ready():
            logging.debug("ZprobeMacro start.")
            self.macro = ZprobeMacro(self._clear_macro)
            self.macro.start(self)

        def toolhead_ready():
            logging.debug("ControlHeaterMacro completed.")
            if self.options.correction == "A":
                logging.debug("CorrectionMacro start.")
                self.macro = CorrectionMacro(correction_ready)
                self.macro.start(self)
            elif self.options.correction == "H":
                logging.debug("ZprobeMacro start.")
                self.macro = ZprobeMacro(self._clear_macro)
                self.macro.start(self)
            else:
                self.fire()

        self.macro = ControlHeaterMacro(toolhead_ready, 0, 170)
        logging.debug("ControlHeaterMacro start.")
        self.macro.start(self)

    def _handle_pause(self):
        # Call only when (status_id == 38 or 50) AND mainboard command queue is
        # becomming EMPTY
        if self.error_symbol:
            errcode = getattr(self.error_symbol, "hw_error_code", 69)
        else:
            errcode = 80

        if self.status_id & 4:
            self.mainboard.send_cmd("X5S%i" % errcode)
            self.paused()

        elif self.mainboard.buffered_cmd_size == 0:
            if self.macro:
                self.mainboard.send_cmd("X5S%i" % errcode)
                if self.macro.giveup(self):
                    self.paused()
                else:
                    logger.debug("Waitting for macro giving up.")
            elif self._mb_stashed:
                self.paused()
            else:
                if self.error_symbol:
                    self.mainboard.send_cmd("C2E%i" % errcode)
                else:
                    self.mainboard.send_cmd("C2E1")
                self._mb_stashed = True

    def pause(self, symbol=None):
        if BaseExecutor.pause(self, symbol):
            if self.mainboard.buffered_cmd_size == 0:
                self._handle_pause()
            return True
        else:
            return False

    def resume(self):
        if BaseExecutor.resume(self):
            self.mainboard.send_cmd("X5S0")
            self.mainboard.bootstrap(self._on_mainboard_ready)
            return True
        else:
            return False

    def _cb_feed_command(self, *args):
        self._cmd_queue.append(args)

    def fire(self):
        if self.status_id == ST_RUNNING and self._eof:
            if self._task_loader.exitcode is not None and \
                    self._task_loader.exitcode > 0:
                raise SystemError(UNKNOWN_ERROR, SUBSYSTEM_ERROR, "TASKLOADER")

            self.status_id = ST_COMPLETING
            fsm = self._fsm
            x, y, z = fsm.get_x(), fsm.get_y(), fsm.get_z()
            if x == x and y == y and z <= 200:
                self.mainboard.send_cmd("G1F10392X0Y0Z205")
            else:
                self.status_id = ST_COMPLETED
                self.close()

        elif self.status_id == ST_RUNNING and not self.macro:
            while (not self._eof) and len(self._cmd_queue) < 24:
                ret = self._fsm.feed(self._task_loader.fileno(),
                                     self._cb_feed_command)
                if ret == 0:
                    self._eof = True
                elif ret == -1:
                    self.abort(RuntimeError(EXEC_BAD_COMMAND, "MOVE"))
                elif ret == -3:
                    self.abort(RuntimeError(EXEC_BAD_COMMAND, "MULTI_E"))

            while self._cmd_queue:
                target = self._cmd_queue[0][1]
                if target == 1:
                    if self.mainboard.queue_full:
                        return
                    else:
                        cmd = self._cmd_queue.popleft()[0]
                        self.mainboard.send_cmd(cmd)
                elif target == 2:
                    if self.mainboard.buffered_cmd_size == 0:
                        if self.toolhead.sendable:
                            cmd = self._cmd_queue.popleft()[0]
                            exec_toolhead_cmd(self.toolhead, cmd)
                        else:
                            return
                    else:
                        return

                elif target == 4:
                    if self.mainboard.buffered_cmd_size == 0:
                        if self.toolhead.sendable:
                            cmd = self._cmd_queue.popleft()[0]
                            self.macro = ControlToolheadMacro(
                                self._clear_macro, cmd)
                            self.macro.start(self)
                    return
                elif target == 8:
                    self.pause(RuntimeError("USER_OPERATION", "FROM_CODE"))
                    self._cmd_queue.popleft()[0]
                    return
                elif target == 128:
                    self.abort(RuntimeError(self._cmd_queue[0][0]))

                else:
                    raise SystemError(UNKNOWN_ERROR, "TARGET=%i" % target)

    def _on_mb_empty(self, sender):
        if self.status_id & 34 == 34:  # PAUSING
            self._handle_pause()
        elif self.status_id & 2 and self.status_id < 32:  # RESUMING
            logger.debug("Mainboard queue empty during resuming")
        elif self.status_id == 48:  # PAUSED
            if self.paused_macro:
                self.paused_macro.on_command_empty(self)
        elif self.macro:
            self.macro.on_command_empty(self)
        elif self.status_id == ST_COMPLETING:
            self.status_id = ST_COMPLETED
            self.close()
        else:
            self.fire()

    def _on_mb_sendable(self, sender):
        if self.status_id == 48:
            if self.paused_macro:
                self.paused_macro.on_command_empty(self)
        elif self.status_id & 16 and self.macro:
            self.macro.on_command_sendable(self)
        else:
            self.fire()

    def _on_mb_ctrl(self, sender, data):
        if self.status_id == 48:
            if self.paused_macro:
                self.paused_macro.on_command_empty(self)

        elif self.macro:
            self.macro.on_ctrl_message(sender, data)

        if data == "STASH_POP":
            if self.status_id == 18:
                self.resumed()
                self.fire()
            else:
                logger.error("Recv stash pop at status: %i", self.status_id)
        else:
            logger.debug("ctrl: %s", data)

    def on_mainboard_recv(self):
        try:
            self.mainboard.handle_recv()
        except RuntimeError as er:
            if not self.pause(er):
                logger.warn("Error occour: %s" % repr(er.args))
        except SystemError as err:
            self.abort(err)
        except Exception as err:
            logger.exception("Error while processing mainboard message")
            if allow_god_mode():
                self.abort(err)
            else:
                self.abort(RuntimeError(UNKNOWN_ERROR, "MAINBAORD_ERROR"))
            raise

    def on_toolhead_recv(self):
        try:
            self.toolhead.handle_recv()
            if self.status_id == ST_RUNNING:
                check_toolhead_errno(self.toolhead, self.th_error_flag)

        except RuntimeError as er:
            # TODO: cut toolhead 5v because pwm issue
            if er.args[:2] == ('HEAD_ERROR', 'HARDWARE_FAILURE'):
                reset_hb()

            if not self.pause(er):
                logger.warn("Error occour: %s" % repr(er.args))

        except SystemError as er:
            self.abort(er)

        except Exception as er:
            logger.exception("Error while processing headboard message")
            if allow_god_mode():
                self.abort(er)
            else:
                self.abort(RuntimeError(UNKNOWN_ERROR, "HEADBOARD_ERROR"))
            raise

    # def load_filament(self, extruder_id):
    #     self.send_mainboard("@\n")
    #
    # def eject_filament(self, extruder_id):
    #     pass

    def on_loop(self):
        try:
            self.mainboard.patrol()
            self.toolhead.patrol()

        except RuntimeError as err:
            if not self.pause(err):
                if self.status_id == ST_RUNNING:
                    raise SystemError("BAD_LOGIC", None, err)
        except SystemError as err:
            self.abort(err)
        except Exception as err:
            logger.exception("Error while processing loop")
            if allow_god_mode():
                self.abort(err)
            else:
                self.abort(RuntimeError(UNKNOWN_ERROR, "LOOP_ERROR"))
            raise

    def close(self):
        self._task_loader.close()
        self.mainboard.close()
        self.toolhead.shutdown()
