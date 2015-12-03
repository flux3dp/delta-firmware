
from collections import deque
import logging

from fluxmonitor.config import DEVICE_POSITION_LIMIT, MAINBOARD_RETRY_TTL
from fluxmonitor.err_codes import UNKNOW_ERROR, EXEC_BAD_COMMAND
from .base import BaseExecutor, ST_STARTING, ST_WAITTING_HEADER  # NOQA
from .base import ST_RUNNING, ST_PAUSING, ST_PAUSED, ST_RESUMING  # NOQA
from .base import ST_ABORTING, ST_ABORTED, ST_COMPLETING, ST_COMPLETED  # NOQA
from .base import ST_STARTING_PAUSED
from .misc import TaskLoader
from ._device_fsm import PyDeviceFSM

from .main_controller import MainController
from .head_controller import get_head_controller, TYPE_3DPRINT

logger = logging.getLogger(__name__)

FLAG_WAITTING_HEADER = 1


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

    def __init__(self, mainboard_io, headboard_io, fileobj, play_bufsize=16):
        self._task_loader = TaskLoader(fileobj)
        super(FcodeExecutor, self).__init__(mainboard_io, headboard_io)

        self._padding_bufsize = max(play_bufsize * 2, 64)

        self.main_ctrl = MainController(
            executor=self, bufsize=play_bufsize,
            ready_callback=self.on_controller_ready,
            retry_ttl=MAINBOARD_RETRY_TTL
        )

        self.head_ctrl = get_head_controller(
            head_type=TYPE_3DPRINT, executor=self,
            ready_callback=self.on_controller_ready,
        )

        self.start()

    def close(self):
        self._task_loader.close()

    def get_status(self):
        st = self.head_ctrl.status()
        st.update(super(FcodeExecutor, self).get_status())
        return st

    def on_controller_ready(self, controller):
        logging.debug("Controller %s ready", controller.__class__.__name__)
        if self.main_ctrl.ready and self.head_ctrl.ready:
            if self.status_id == ST_STARTING:
                self._do_startup()
            elif self.status_id == ST_RESUMING:
                if self._ctrl_flag & FLAG_WAITTING_HEADER:
                    self._ctrl_flag &= ~FLAG_WAITTING_HEADER
                self.main_ctrl.send_cmd("C2F", self)
                self._mb_stashed = False

    def _do_startup(self):
        try:
            self.main_ctrl.send_cmd("T0", self)   # Select extruder 0
            self.main_ctrl.send_cmd("G21", self)  # Set units to mm
            self.main_ctrl.send_cmd("G90", self)  # Absolute Positioning
            self.main_ctrl.send_cmd("G92E0", self)  # Set E to 0
            self.main_ctrl.send_cmd("G28", self)  # Home
        except Exception as e:
            logging.exception("Error while send init gcode")
            raise SystemError("UNKNOW_ERROR", e)

        self.main_ctrl.callback_msg_empty = self._on_startup_complete

    def _on_startup_complete(self, sender):
        self.status_id = ST_RUNNING
        self._cmd_queue = deque()
        self._ctrl_flag = 0

        self.main_ctrl.callback_msg_empty = self._on_mainboard_empty
        self.main_ctrl.callback_msg_sendable = self._on_mainboard_sendable

        self._fsm = PyDeviceFSM(max_x=DEVICE_POSITION_LIMIT[0],
                                max_y=DEVICE_POSITION_LIMIT[1],
                                max_z=DEVICE_POSITION_LIMIT[2])
        self.fire()

    def pause(self, *args):
        if BaseExecutor.pause(self, *args):
            pass
            if self.status_id == ST_STARTING_PAUSED:
                pass
            elif self.status_id == ST_PAUSING:
                if self._mb_stashed:
                    self.status_id = ST_PAUSED
                else:
                    if self.main_ctrl.buffered_cmd_size == 0:
                        self.main_ctrl.send_cmd("C2O", self)
                        self._mb_stashed = True
            return True
        else:
            return False

    def resume(self):
        if BaseExecutor.resume(self):
            if self.status_id == ST_STARTING:
                self.head_ctrl.bootstrap(self)
                self.on_controller_ready(None)
            elif self.status_id == ST_RESUMING:
                self.head_ctrl.bootstrap(self)
            return True
        else:
            return False

    def resumed(self):
        BaseExecutor.resumed(self)
        self.fire()

    def abort(self, *args):
        if BaseExecutor.abort(self, *args):
            self.main_ctrl.close(self)
            return True
        else:
            return False

    def fire(self):
        if self.status_id == ST_RUNNING:
            while (not self._eof) and len(self._cmd_queue) < 24:
                ret = self._fsm.feed(self._task_loader.fileno(),
                                     self._cb_feed_command)
                if ret == 0:
                    self._eof = True
                elif ret == -1:
                    self.abort(EXEC_BAD_COMMAND, "MOVE")
                elif ret == -3:
                    self.abort(EXEC_BAD_COMMAND, "MULTI_E")

            if (self._ctrl_flag & FLAG_WAITTING_HEADER) == 0:
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
                            self._ctrl_flag |= FLAG_WAITTING_HEADER
                            cmd = self._cmd_queue.popleft()[0]
                            if not self.head_ctrl.is_busy:
                                self.head_ctrl.send_cmd(cmd, self,
                                                        self._cb_head_ready)
                            return
                        else:
                            return
                    elif target == 128:
                        self.abort(self._cmd_queue[0][0])

                    else:
                        raise SystemError("UNKNOW_ERROR", "target=%i" % target)

    def _cb_feed_command(self, *args):
        self._cmd_queue.append(args)

    def _cb_head_ready(self, sender):
        self._ctrl_flag &= ~FLAG_WAITTING_HEADER
        self.fire()

    def _on_mainboard_empty(self, sender):
        if self.status_id == ST_RUNNING and self._eof:
            self.status_id = ST_COMPLETING
            self.main_ctrl.send_cmd("G28", self)
        elif self.status_id == ST_COMPLETING:
            self.main_ctrl.close(self)
            self.status_id = ST_COMPLETED
        elif self.status_id == ST_PAUSING:
            if self._mb_stashed:
                self.status_id = ST_PAUSED
            else:
                self.main_ctrl.send_cmd("C2O", self)
                self._mb_stashed = True
        elif self.status_id == ST_RESUMING:
            if self._mb_stashed:
                self.main_ctrl.send_cmd("C2F", self)
                self._mb_stashed = False
            else:
                self.resumed()
        else:
            self.fire()

    def _on_mainboard_sendable(self, sender):
        self.fire()

    def on_mainboard_message(self, msg):
        try:
            self.main_ctrl.on_message(msg, self)
            self.fire()
        except RuntimeError as err:
            if not self.pause(*err.args):
                raise SystemError("BAD_LOGIC")
        except SystemError as err:
            self.abort(*err.args)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Unhandle error")
            self.abort(UNKNOW_ERROR, "MAINBOARD_MESSAGE")

    def on_headboard_message(self, msg):
        try:
            self.head_ctrl.on_message(msg, self)
            self.fire()
        except RuntimeError as err:
            if not self.pause(*err.args):
                if self.status_id == ST_RUNNING:
                    raise SystemError("BAD_LOGIC")
        except SystemError as err:
            self.abort(*err.args)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Unhandle error")
            self.abort(UNKNOW_ERROR, "HEADBOARD_MESSAGE")

    # def load_filament(self, extruder_id):
    #     self.send_mainboard("@\n")
    #
    # def eject_filament(self, extruder_id):
    #     pass
    #
    def on_loop(self):
        try:
            self.main_ctrl.patrol(self)
            self.head_ctrl.patrol(self, (self.status_id == ST_STARTING or
                                         self.status_id == ST_RUNNING or
                                         self.status_id == ST_RESUMING))
        except RuntimeError as err:
            if not self.pause(err.args[0]):
                if self.status_id == ST_RUNNING:
                    raise SystemError("BAD_LOGIC")
        except SystemError as err:
            self.abort(*err.args)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Unhandle error")
            self.abort(UNKNOW_ERROR, "LOOPBACK")
