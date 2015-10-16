

from datetime import datetime
import logging

L = logging.getLogger(__name__)

# 1   STARTING/RESUMING flag
# 2   PAUSING flag
# 4   ABORTING/COMPLETING flag
# 16  RUNNING
# 32  PAUSED
# 64  COMPLETED
# 128 ABORTED


ST_STARTING = 1


ST_WAITTING_HEADER = "WAITTING_HEADER"
# ST_HEATING = "HEATING"

ST_RESUMING = 17  # 1 + 16
ST_RUNNING = 16

ST_STARTING_PAUSED = 32  # 32

ST_PAUSING = 50  # 2 + 16 + 32
ST_PAUSED = 48  # 16 + 32

ST_COMPLETING = 68  # 4 + 64
ST_COMPLETED = 64

ST_ABORTING = 132  # 4 + 128
ST_ABORTED = 128


STATUS_MSG = {
    ST_STARTING: "STARTING",
    ST_RUNNING: "RUNNING",
    ST_PAUSING: "PAUSING",

    ST_STARTING_PAUSED: "PAUSED",
    ST_PAUSED: "PAUSED",
    ST_RESUMING: "RESUMING",

    ST_ABORTING: "ABORTING",
    ST_ABORTED: "ABORTED",

    ST_COMPLETING: "COMPLETING",
    ST_COMPLETED: "COMPLETED",
}


L = logging.getLogger(__name__)


class BaseExecutor(object):
    _status = None
    _err_symbol = None
    time_used = 0

    def __init__(self, mainboard_io, headboard_io):
        self.__mbio = mainboard_io
        self.__hbio = headboard_io
        self._status = ST_STARTING

    def start(self):
        self.__begin_at = self.__start_at = datetime.now().utcnow()

    def pause(self, main_info, minor_info=None):
        nst = -1
        if self._status == ST_STARTING:
            nst = ST_STARTING_PAUSED
        elif self._status == ST_RESUMING or self._status == ST_RUNNING:
            nst = ST_PAUSED

        if nst > 0:
            L.debug("ST %3i -> %3i:%s", self._status, nst, main_info)
            self._status = nst
            self._err_symbol = (main_info, minor_info)
            return True
        else:
            L.debug("Pause Rejected: %s" % main_info)
            return False

    def paused(self):
            L.debug("Paused")
            t = datetime.now().utcnow()
            self.time_used += (t - self.__start_at).total_seconds()
            self.__start_at = None
            self._status = ST_PAUSED

    def resume(self):
        nst = -1
        if self._status == ST_PAUSED:
            nst = ST_RESUMING
        elif self._status == ST_STARTING_PAUSED:
            nst = ST_STARTING

        if nst > 0:
            L.debug("ST %3i -> %3i:%s", self._status, nst, "RESUME")
            self._status = nst
            return True
        else:
            return False

    def resumed(self):
        L.debug("Resumed")
        self.__start_at = datetime.now().utcnow()
        self._status = ST_RUNNING

    def abort(self, main_err, minor_info=None):
        if (self._status & 192) == 0:
            L.debug("Abort: %s %s" % (main_err, minor_info))
            # TODO
            self._status = ST_ABORTED
            self._err_symbol = (main_err, minor_info)
            return True
        else:
            return False

    def get_status(self):
        st = {
            "st_id": self._status,
            "st_label": STATUS_MSG.get(self._status, "UNKNOW_STATUS"),
        }
        if (self._status & 160) > 0:
            st["error"] = self._err_symbol
        return st

    def is_closed(self):
        return (self._status & 192) > 0

    def send_mainboard(self, msg):
        if self.__mbio.send(msg) != len(msg):
            raise Exception("DIE")

    def send_headboard(self, msg):
        self.__hbio.send(msg)
