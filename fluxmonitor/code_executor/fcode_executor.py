
from collections import deque
from time import time
import logging
import os

from fluxmonitor.err_codes import UNKNOW_ERROR
from .base import BaseExecutor, ST_STARTING, ST_WAITTING_HEADER, ST_RUNNING, \
    ST_PAUSED, ST_RESUMING, ST_ABORTING, ST_ABORTED, \
    ST_COMPLETING, ST_COMPLETED
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
    _task_loader = None
    _fsm = None
    _eof = False

    def __init__(self, mainboard_io, headboard_io, fileobj, play_bufsize=16):
        super(FcodeExecutor, self).__init__(mainboard_io, headboard_io)

        self._task_loader = TaskLoader(fileobj)
        self._padding_bufsize = max(play_bufsize * 2, 64)

        self.main_ctrl = MainController(
            executor=self, bufsize=play_bufsize,
            ready_callback=self.on_controller_ready,
        )

        self.head_ctrl = get_head_controller(
            head_type=TYPE_3DPRINT, executor=self,
            ready_callback=self.on_controller_ready,
        )

        self.start()

    def on_controller_ready(self, controller):
        if self.main_ctrl.ready and self.head_ctrl.ready:
            if self._status == ST_STARTING:
                self._do_startup()

    def _do_startup(self):
        try:
            self.main_ctrl.send_cmd("T0", self)   # Select extruder 0
            self.main_ctrl.send_cmd("G21", self)  # Set units to mm
            self.main_ctrl.send_cmd("G90", self)  # Absolute Positioning
            self.main_ctrl.send_cmd("G28", self)  # Home
        except Exception as e:
            logging.exception("Error while send init gcode")
            raise SystemError("UNKNOW_ERROR", e)

        self.main_ctrl.callback_msg_empty = self._on_startup_complete

    def _on_startup_complete(self, sender):
        self._status = ST_RUNNING
        self._cmd_queue = deque()
        self._ctrl_flag = 0

        self.main_ctrl.callback_msg_empty = self._on_mainboard_empty
        self.main_ctrl.callback_msg_sendable = self._on_mainboard_sendable

        self._fsm = PyDeviceFSM()
        self.fire()

    def abort(self, *args):
        if BaseExecutor.abort(self, *args):
            self.main_ctrl.close(self)
            return True
        else:
            return False

    def fire(self):
        if self._status == ST_RUNNING:
            while (not self._eof) and len(self._cmd_queue) < 24:
                if self._fsm.feed(self._task_loader.fileno(),
                                  self._cb_feed_command) == 0:
                    self._eof = True

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
                    else:
                        raise SystemError("UNKNOW_ERROR", "target=%i" % target)

    def _cb_feed_command(self, *args):
        self._cmd_queue.append(args)

    def _cb_head_ready(self, sender):
        self._ctrl_flag &= ~FLAG_WAITTING_HEADER
        self.fire()

    def _on_mainboard_empty(self, sender):
        if self._status == ST_RUNNING and self._eof:
            self._status = ST_COMPLETING
            self.main_ctrl.send_cmd("G28", self)
        elif self._status == ST_COMPLETING:
            self.main_ctrl.close(self)
            self._status = ST_COMPLETED
        else:
            self.fire()

    def _on_mainboard_sendable(self, sender):
        self.fire()

    def on_mainboard_message(self, msg):
        try:
            self.main_ctrl.on_message(msg, self)
            self.fire()
        except RuntimeError as err:
            if not self.pause(err.args[0]):
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
            if not self.pause(err.args[0]):
                raise SystemError("BAD_LOGIC")
        except SystemError as err:
            self.abort(*err.args)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Unhandle error")
            self.abort(UNKNOW_ERROR, "HEADBOARD_MESSAGE")

    def on_loop(self, sender):
        try:
            self.main_ctrl.patrol(self)
            self.head_ctrl.patrol(self)
        except RuntimeError as err:
            if not self.pause(err.args[0]):
                self.abort("BAD_LOGIC", err.args[0])
        except SystemError as err:
            self.abort(*err.args)
        except Exception as err:
            if self.debug:
                raise
            logger.exception("Unhandle error")
            self.abort(UNKNOW_ERROR, "LOOPBACK")

