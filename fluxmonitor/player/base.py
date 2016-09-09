

from datetime import datetime
from time import time
import logging

L = logging.getLogger(__name__)

ST_INIT = 1
ST_STARTING = 4
ST_RUNNING = 16
ST_PAUSED = 32
ST_COMPLETED = 64
ST_ABORTED = 128

ST_STARTING_PAUSED = ST_STARTING + ST_PAUSED
ST_STARTING_PAUSING = ST_STARTING_PAUSED + 2
ST_RUNNING_PAUSED = ST_RUNNING + ST_PAUSED
ST_RUNNING_PAUSING = ST_RUNNING_PAUSED + 2

ST_STARTING_RESUMING = ST_STARTING + 2
ST_RUNNING_RESUMING = ST_RUNNING + 2

ST_COMPLETING = ST_COMPLETED + 2


STATUS_MSG = {
    ST_STARTING: "STARTING",
    ST_RUNNING: "RUNNING",
    ST_COMPLETED: "COMPLETED",
    ST_ABORTED: "ABORTED",

    ST_STARTING_PAUSING: "PAUSING",
    ST_RUNNING_PAUSING: "PAUSING",

    ST_STARTING_PAUSED: "PAUSED",
    ST_RUNNING_PAUSED: "PAUSED",

    ST_STARTING_RESUMING: "RESUMING",
    ST_RUNNING_RESUMING: "RESUMING",

    ST_COMPLETING: "COMPLETING"
}


L = logging.getLogger(__name__)


class BaseExecutor(object):
    status_id = None
    error_symbol = None
    time_used = 0
    macro = None
    __start_at = 0

    def __init__(self, mainboard_io, headboard_io):
        self.__mbio = mainboard_io
        self.__hbio = headboard_io
        self.status_id = ST_INIT

    def start(self):
        self.status_id = ST_STARTING
        self.__begin_at = datetime.now().utcnow()

    def started(self):
        if self.status_id != 4:
            raise Exception("BAD_LOGIC")
        self.status_id = 16  # status_id = ST_RUNNING
        L.debug("GO!")
        self.__start_at = time()

    def pause(self, symbol=None):
        if self.status_id & 224:
            # Completed/Aborted/Paused or goting to be
            L.debug("Pause rejected: %s" % symbol)

            if self.error_symbol is None:
                # Update error label only
                self.error_symbol = symbol
            return False

        nst = self.status_id | ST_PAUSED | 2
        L.debug("ST %3i -> %3i: %s", self.status_id, nst, symbol)
        self.status_id = nst
        self.error_symbol = symbol

        if self.__start_at:
            self.time_used += (time() - self.__start_at)
        self.__start_at = None

        return True

    def paused(self):
        if self.status_id & 192:
            L.error("PAUSED invoke at complete/abort")
            return

        nst = (self.status_id | ST_PAUSED) & ~2
        L.debug("ST %3i -> %3i: PAUSED", self.status_id, nst)
        self.status_id = nst

    def resume(self):
        if self.status_id & 192:
            # Completed/Aborted or goting to be
            L.debug("Resume rejected")
            return False
        elif self.status_id & 34 == 32:
            # Paused
            nst = (self.status_id & ~ST_PAUSED) | 2
            L.debug("ST %3i -> %3i: RESUMING", self.status_id, nst)
            self.status_id = nst
            self.error_symbol = None
            return True
        else:
            L.debug("Resume rejected at status: %i", self.status_id)
            return False

    def resumed(self):
        if self.status_id & 192:
            L.error("RESUMED invoke at complete/abort")
            return

        nst = (self.status_id & ~ST_PAUSED) & ~2
        L.debug("ST %3i -> %3i: RESUMED", self.status_id, nst)
        self.status_id = nst
        self.__start_at = time()

    def abort(self, symbol=None):
        if self.status_id & 192:
            # Completed/Aborted or goting to be
            L.debug("Abort rejected")
            return False

        L.debug("Abort: %s" % symbol)
        self.status_id = ST_ABORTED
        self.error_symbol = symbol
        return True

    @property
    def error_str(self):
        if self.error_symbol:
            return " ".join(self.error_symbol.args)
        else:
            return ""

    def get_status(self):
        st_id = self.status_id
        return {
            "st_id": st_id,
            "st_label": self.macro.name if self.macro else STATUS_MSG.get(
                st_id, "UNKNOW_STATUS"),
            "error": self.error_symbol.args if self.error_symbol else []
        }

    def is_closed(self):
        return self.status_id and (self.status_id & ~192) == 0

    def close(self):
        self.__mbio.close()
        self.__hbio.close()

    def send_mainboard(self, msg):
        if self.__mbio.send(msg) != len(msg):
            raise Exception("DIE")

    def send_headboard(self, msg):
        self.__hbio.send(msg)
