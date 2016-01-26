
from collections import deque
import logging

from fluxmonitor.config import MAINBOARD_RETRY_TTL
from fluxmonitor.err_codes import UNKNOWN_ERROR, EXEC_BAD_COMMAND
from fluxmonitor.diagnosis.god_mode import allow_god_mode

from .base import BaseExecutor
from .base import ST_STARTING, ST_RUNNING, ST_COMPLETED, ST_ABORTED  # noqa
from .base import ST_COMPLETING
from ._device_fsm import PyDeviceFSM
from .macro import StartupMacro, CorrectionMacro, ZprobeMacro, WaitHeadMacro

from .main_controller import MainController
from .head_controller import HeadController

logger = logging.getLogger(__name__)


class FcodeExecutor(BaseExecutor):
    debug = False  # Note: debug only use for unittest
    main_ctrl = None
    head_ctrl = None
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

        self.main_ctrl = MainController(
            executor=self, bufsize=options.play_bufsize,
            ready_callback=self.on_controller_ready,
            retry_ttl=MAINBOARD_RETRY_TTL
        )

        self.head_ctrl = HeadController(
            executor=self, ready_callback=self.on_controller_ready,
            required_module=options.head,
            error_level=self.options.head_error_level
        )

        self.main_ctrl.callback_msg_empty = self._on_mainboard_empty
        self.main_ctrl.callback_msg_sendable = self._on_mainboard_sendable

        self.start()

        self._fsm = PyDeviceFSM(max_x=self.options.max_x,
                                max_y=self.options.max_y,
                                max_z=self.options.max_z)

    @property
    def traveled(self):
        return self._fsm.get_traveled()

    def close(self):
        self._task_loader.close()

    def get_status(self):
        st = self.head_ctrl.status()
        st.update(super(FcodeExecutor, self).get_status())
        return st

    def on_controller_ready(self, controller):
        logging.debug("Controller %s ready", controller)
        if self.main_ctrl.ready and self.head_ctrl.ready:
            if self.status_id & 32:
                return

            if self.status_id == 6:
                self.resumed()

            if self.status_id == 4:  # if status_id == ST_STARTING
                self.started()
            else:
                self._process_resume()

    def on_macro_complete(self):
        logging.debug("Macro complete: %s", self.macro)
        macro = self.macro
        self.macro = None
        if isinstance(macro, StartupMacro):
            assert not self._cmd_queue

            self._cmd_queue = deque()
            self._fsm.set_max_exec_time(0.1)

            if self.options.correction in ("A", "H"):
                self.macro = WaitHeadMacro(self.on_preheating_complete,
                                           "H0170")
                if self.status_id == ST_RUNNING:
                    logging.debug("Start macro: WaitHeadMacro(\"H0170\")")
                    self.macro.start(self)
            else:
                self.fire()

        elif isinstance(macro, CorrectionMacro):
            self.macro = ZprobeMacro(self.on_macro_complete)
            if self.status_id == ST_RUNNING:
                logging.debug("Start macro: %s", self.macro)
                self.macro.start(self)

        elif isinstance(macro, ZprobeMacro):
            self.fire()

        elif isinstance(macro, WaitHeadMacro):
            self.fire()

        else:
            self.fire()

    def on_preheating_complete(self):
        logging.debug("Macro complete: %s", self.macro)
        self.macro = None
        if self.options.correction == "A":
            logging.debug("Run macro: CorrectionMacro")
            self.macro = CorrectionMacro(self.on_macro_complete)
            logging.debug("Start macro: %s", self.macro)
            self.macro.start(self)
        elif self.options.correction == "H":
            logging.debug("Run macro: ZprobeMacro")
            self.macro = ZprobeMacro(self.on_macro_complete)
            logging.debug("Start macro: %s", self.macro)
            self.macro.start(self)
        else:
            self.fire()

    def started(self):
        super(FcodeExecutor, self).started()
        self.macro = StartupMacro(self.on_macro_complete, self.options)
        self.macro.start(self)

    def _process_pause(self):
        if self.error_symbol:
            errcode = getattr(self.error_symbol, "hw_error_code", 69)
        else:
            errcode = 80

        if self.status_id & 4:
            self.main_ctrl.send_cmd("X5S%i" % errcode, self)
            self.paused()

        elif self.main_ctrl.buffered_cmd_size == 0:
            if self.macro:
                self.main_ctrl.send_cmd("X5S%i" % errcode, self)
                self.paused()
                self.macro.giveup()
            elif self._mb_stashed:
                self.paused()
            else:
                if self.error_symbol:
                    self.main_ctrl.send_cmd("C2E%i" % errcode, self)
                else:
                    self.main_ctrl.send_cmd("C2E1", self)
                self._mb_stashed = True

    def _process_resume(self):
        if self.main_ctrl.ready and self.head_ctrl.ready:
            if self.main_ctrl.buffered_cmd_size == 0:
                if self.head_ctrl.allset:
                    if self._mb_stashed:
                        self.main_ctrl.send_cmd("C2F", self)
                        self._mb_stashed = False
                    else:
                        self.resumed()
                        if self.status_id & 4:
                            self.started()
                        else:
                            if self.macro:
                                self.macro.start(self)
                            else:
                                self.fire()
                else:
                    def on_allset():
                        self.on_controller_ready(self.head_ctrl)

                    m = WaitHeadMacro(on_allset)
                    m.start(self)

    def pause(self, symbol=None):
        if BaseExecutor.pause(self, symbol):
            self._process_pause()
            return True
        else:
            return False

    def resume(self):
        if BaseExecutor.resume(self):
            self.main_ctrl.send_cmd("X5S0", self)

            if self.main_ctrl.ready and self.head_ctrl.ready:
                self._process_resume()
            else:
                if not self.main_ctrl.ready:
                    self.main_ctrl.bootstrap(self)
                if not self.head_ctrl.ready:
                    self.head_ctrl.bootstrap(self)
            return True
        else:
            return False

    def abort(self, symbol=None):
        if BaseExecutor.abort(self, symbol):
            self.main_ctrl.close(self)
            return True
        else:
            return False

    def fire(self):
        if not self.macro and self.status_id == ST_RUNNING:
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
                    if self.main_ctrl.queue_full:
                        return
                    else:
                        cmd = self._cmd_queue.popleft()[0]
                        self.main_ctrl.send_cmd(cmd, self)
                elif target == 2:
                    if self.main_ctrl.buffered_cmd_size == 0:
                        cmd = self._cmd_queue.popleft()[0]
                        if self.head_ctrl.is_busy:
                            return
                        else:
                            self.head_ctrl.send_cmd(cmd, self)
                    else:
                        return

                elif target == 4:
                    if self.main_ctrl.buffered_cmd_size == 0:
                        if not self.head_ctrl.is_busy:
                            cmd = self._cmd_queue.popleft()[0]
                            self.macro = WaitHeadMacro(self.on_macro_complete,
                                                       cmd)
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

    def _cb_feed_command(self, *args):
        self._cmd_queue.append(args)

    def _on_mainboard_empty(self, sender):
        if self.status_id & 34 == 34:  # PAUSING
            self._process_pause()
        elif self.status_id & 2 and self.status_id < 32:  # RESUMING
            self._process_resume()
        elif self.macro:
            self.macro.on_command_empty(self)
        elif self.status_id == ST_RUNNING and self._eof and \
                not self._cmd_queue:
            self.status_id = ST_COMPLETING
            fsm = self._fsm
            x, y, z = fsm.get_x(), fsm.get_y(), fsm.get_z()
            if x == x and y == y and z <= 200:
                self.main_ctrl.send_cmd("G1F6000X0Y0Z205", self)
            else:
                self.status_id = ST_COMPLETED
                self.main_ctrl.close(self)

        elif self.status_id == ST_COMPLETING:
            self.status_id = ST_COMPLETED
            self.main_ctrl.close(self)
        else:
            self.fire()

    def _on_mainboard_sendable(self, sender):
        if self.macro:
            self.macro.on_command_sendable(self)
        else:
            self.fire()

    def on_mainboard_message(self, msg):
        try:
            if self.macro:
                self.macro.on_mainboard_message(msg, self)

            self.main_ctrl.on_message(msg, self)
            self.fire()
        except RuntimeError as err:
            if not self.pause(err):
                logger.warn("Error occour: %s" % repr(err.args))
        except SystemError as err:
            self.abort(err)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Error while processing mainboard message")
            if allow_god_mode():
                self.abort(err)
            else:
                self.abort(RuntimeError(UNKNOWN_ERROR, "MAINBAORD_ERROR"))

    def on_headboard_message(self, msg):
        try:
            if self.macro:
                self.macro.on_headboard_message(msg, self)

            self.head_ctrl.on_message(msg, self)
            self.fire()
        except RuntimeError as err:
            if not self.pause(err):
                logger.warn("Error occour: %s" % repr(err.args))
        except SystemError as err:
            self.abort(err)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Error while processing headboard message")
            if allow_god_mode():
                self.abort(err)
            else:
                self.abort(RuntimeError(UNKNOWN_ERROR, "HEADBOARD_ERROR"))

    # def load_filament(self, extruder_id):
    #     self.send_mainboard("@\n")
    #
    # def eject_filament(self, extruder_id):
    #     pass
    #

    def on_loop(self):
        try:
            self.main_ctrl.patrol(self)
            self.head_ctrl.patrol(self)

        except RuntimeError as err:
            if not self.pause(err):
                if self.status_id == ST_RUNNING:
                    raise SystemError("BAD_LOGIC", None, err)
        except SystemError as err:
            self.abort(err)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Error while processing loop")
            if allow_god_mode():
                self.abort(err)
            else:
                self.abort(RuntimeError(UNKNOWN_ERROR, "LOOP_ERROR"))
