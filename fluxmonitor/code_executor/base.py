

from datetime import datetime
import logging

from .main_controller import MainController
from .head_controller import ExtruderController

ST_STARTING = "STARTING"

ST_WAITTING_HEADER = "WAITTING_HEADER"
# ST_HEATING = "HEATING"
#
# ST_CALIBRATION = "CALIBRATION"
ST_RUNNING = "RUNNING"
ST_PAUSING = "PAUSING"
ST_PAUSED = "PAUSE"
ST_RESUMING = "RESUMING"

ST_ABORTING = "ABORTING"
ST_ABORTED = "ABORTED"

ST_COMPLETING = "COMPLETING"
ST_COMPLETED = "COMPLETED"

L = logging.getLogger(__name__)


class BaseExecutor(object):
    main_lineno = -1
    time_used = 0
    _status = None
    _err_symbol = None

    def __init__(self, mainboard_io, headboard_io):
        self.__mbio = mainboard_io
        self.__hbio = headboard_io
        self._status = ST_STARTING

    def start(self):
        self.__begin_at = self.__start_at = datetime.now().utcnow()

    def pause(self, reason):
        if self._status == ST_RUNNING:
            L.debug("Pause: %s" % reason)
            self._status = ST_PAUSING
            return True
        else:
            return False

    def paused(self):
            L.debug("Paused")
            t = datetime.now().utcnow()
            self.time_used += (t - self.__start_at).total_seconds()
            self.__start_at = None
            self._status = ST_PAUSED

    def resume(self):
        if self._status == ST_PAUSED:
            L.debug("Resume")
            self._status = ST_STARTING
            return True
        else:
            return False

    def resumed(self):
        L.debug("Resumed")
        self.__start_at = datetime.now().utcnow()
        self._status = ST_RUNNING

    def abort(self, main_err, minor_err=None):
        if self._status not in [ST_COMPLETED, ST_ABORT]:
            L.debug("Abort: %s %s" % (main_err, minor_err))
            self._status = ST_ABORT
            self._err_symbol = (main_err, minor_err)

    def get_status(self):
        if self._status == ST_ABORT:
            return {"status": ST_ABORT, "error": self._err_symbol[0]}
        else:
            return {"status": self._status}

    def is_closed(self):
        return self._status in [ST_ABORTED, ST_COMPLETED]

    def send_mainboard(self, msg):
        if self.__mbio.send(msg) != len(msg):
            raise Exception("DIE")

    def send_headboard(self, msg):
        self.__hbio.send(msg)

