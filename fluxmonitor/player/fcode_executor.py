
from collections import deque
import logging

from fluxmonitor.diagnosis.god_mode import allow_god_mode
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.diagnosis.tracer import tracer
from fluxmonitor.err_codes import (UNKNOWN_ERROR, EXEC_BAD_COMMAND,
                                   SUBSYSTEM_ERROR)
from fluxmonitor.hal.tools import reset_hb, toolhead_on, toolhead_standby

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

STASHING_FLAG = 1
STASHED_FLAG = 2
TOOLHEAD_STANDINGBY_FLAG = 4
TOOLHEAD_STANDBY_FLAG = 8


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
    _pause_flags = 0
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
        # status_id should be (4, 6, 18, 48)
        # Mainboard should be ready
        def callback(toolhead):
            if self.toolhead.allset:
                self._on_toolhead_recovered_and_allset(self.toolhead)
            else:
                m = WaitHeadMacro(self._on_toolhead_recovered_and_allset)
                m.start(self)

        if self.toolhead.module_name != "N/A":
            logger.debug("Set toolhead mode: operating")
            toolhead_on()

        if self.status_id & ST_RUNNING:
            self.toolhead.recover(callback)
        else:
            self._on_toolhead_recovered_and_allset(self.toolhead)

    def _on_toolhead_recovered_and_allset(self, *args):
        # status_id should be (4, 6, 18, 48)
        # Mainboard should be ready
        # Toolhead should be ready
        # Toolhead status should be allset
        self._pause_flags &= ~TOOLHEAD_STANDBY_FLAG
        if self.status_id == 4 or self.status_id == 6:
            self.started()
        elif self.status_id == 18:
            if self._pause_flags & STASHED_FLAG:
                self._pause_flags &= ~STASHED_FLAG
                self.mainboard.send_cmd("C2F")
            else:
                self.resumed()
        elif self.status_id == 48:
            logger.debug("Toolhead ready and all set during paused")
        else:
            logger.error("Unknown action for status %i in "
                         "on_toolhead_recovered_and_allset.", self.status_id)

    def _pause_toolhead(self, sender=None):
        if self.toolhead.ready:
            if self.toolhead.sendable():
                self._pause_flags |= TOOLHEAD_STANDINGBY_FLAG
                self.toolhead.standby(self._toolhead_paused)
                logger.debug("Standby toolhead.")
            else:
                logger.debug("Waitting toolhead complete command.")
                self.toolhead.set_command_callback(self._pause_toolhead)
        else:
            logger.debug("Ignore standby toolhead because it is not ready.")
            self._toolhead_paused()

    def _toolhead_paused(self, sender=None):
        if self.status_id == 50 or self.status_id == 48:
            logger.debug("Toolhead standby completed.")
            self._pause_flags &= ~TOOLHEAD_STANDINGBY_FLAG

            if self.toolhead.ready:
                self._pause_flags |= TOOLHEAD_STANDBY_FLAG
            else:
                self._pause_flags &= ~TOOLHEAD_STANDBY_FLAG

            if self.status_id == 50:
                self.paused()

            logger.debug("Set toolhead mode: standby")
            toolhead_standby()
        else:
            logger.error("Unknown action for status %i in toolhead_paused. ",
                         self.status_id)

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

        if self.status_id == 38:
            self.mainboard.send_cmd("X5S%i" % errcode)
            self.paused()

        elif self.status_id == 50:
            if self.mainboard.buffered_cmd_size:
                logger.debug("Waitting mainboard command clear (caller=%s)",
                             tracer)
            else:
                if self.macro and self.macro.giveup(self) is False:
                    logger.debug("Waitting macro giving up (caller=%s)",
                                 tracer)
                elif self._pause_flags & (STASHING_FLAG | STASHED_FLAG) == 0:
                    # Ready for maincoard pause...

                    self._pause_flags |= STASHING_FLAG
                    stash_cmd = "C2"
                    if self.error_symbol:
                        stash_cmd += "E%i" % errcode
                    else:
                        stash_cmd += "E1"

                    if self.macro:
                        stash_cmd += "Z0"

                    self.mainboard.send_cmd(stash_cmd)
                else:
                    logger.debug("Nothing to do in handle_pause")
        else:
            logger.error("Unknown action for status %i in handle_pause.",
                         self.status_id)

    # public interface
    def set_toolhead_operation(self):
        if self.status_id == 48:
            self.toolhead.bootstrap(self._on_toolhead_ready)
            return True
        else:
            logger.warning("Can not set toolhead operation mode at status %i",
                           self.status_id)
            return False

    # public interface
    def set_toolhead_standby(self):
        if self.status_id == 48 and self.toolhead.ready:
            self._pause_toolhead()
            return True
        else:
            return False

    # def load_filament(self, extruder_id):
    #     self.send_mainboard("@\n")
    #
    # def eject_filament(self, extruder_id):
    #     pass

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

    def resumed(self):
        BaseExecutor.resumed(self)
        if self.macro:
            logger.debug("Re-start macro: %s", self.macro.name)
            self.macro.start(self)
        else:
            self.fire()

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
            self.macro.on_ctrl_message(self, data)

        if data == "STASH_POP":
            if self.status_id == 18:
                self.resumed()
            else:
                logger.error("Recv 'STASH_POP' at status: %i", self.status_id)
        elif data == "STASH":
            if self.status_id == 50:
                self._pause_flags &= ~STASHING_FLAG
                self._pause_flags |= STASHED_FLAG

                self._pause_toolhead()
            else:
                logger.error("Recv 'STASH' at status: %i", self.status_id)
        else:
            logger.debug("ctrl: %s", data)

    def on_mainboard_recv(self):
        try:
            self.mainboard.handle_recv()
        except IOError:
            self.abort(SystemError(SUBSYSTEM_ERROR, "MAINBAORD_ERROR"))
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
        except IOError:
            self.abort(SystemError(SUBSYSTEM_ERROR, "TOOLHEAD_ERROR"))
        except RuntimeError as er:
            if not self.toolhead.ready:
                self._pause_flags &= ~TOOLHEAD_STANDINGBY_FLAG
                self._pause_flags |= TOOLHEAD_STANDINGBY_FLAG

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
                self.abort(RuntimeError(UNKNOWN_ERROR, "TOOLHEAD_ERROR"))
            raise

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
        try:
            self.mainboard.close()
        except IOError as er:
            logger.error("Mainboard close error: %s", er)
        except Exception:
            logger.exception("Mainboard close error")

        try:
            logger.debug("Set toolhead mode: standby")
            toolhead_standby()
            self.toolhead.shutdown()
        except IOError as er:
            logger.error("Toolhead shutdown error: %s", er)
        except Exception:
            logger.exception("Mainboard close error")
