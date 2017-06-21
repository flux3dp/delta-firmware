

from fluxmonitor.misc.systime import systime as time
from hashlib import md5
import logging
import os

logger = logging.getLogger(__name__)

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


class Timer(object):
    __begin_at = None
    __start_at = None
    __sum = 0

    def start_timer(self):
        if self.__begin_at:
            self.__start_at = time()
        else:
            self.__start_at = self.__begin_at = time()

    def pause_timer(self):
        if self.__start_at:
            self.__sum = time() - self.__start_at
            self.__start_at = None

    @property
    def total_used_times(self):
        # Return time from started
        return time() - self.__begin_at

    @property
    def used_times(self):
        # Return time during running status
        if self.__start_at:
            return self.__sum + (time() - self.__start_at)
        else:
            return self.__sum


class BaseExecutor(Timer):
    status_id = None
    error_symbol = None
    macro = None
    paused_macro = None

    def __init__(self, mainboard_sock, toolhead_sock):
        self.session = md5(os.urandom(64)).hexdigest()[:6]
        self._mbsock = mainboard_sock
        self._thsock = toolhead_sock
        self.status_id = ST_INIT
        self.start_timer()
        logger.info("Initialize (status=%i)", self.status_id)

    def start(self):
        self.status_id = ST_STARTING
        logger.info("Starting (status=%i)", self.status_id)

    def started(self):
        if self.status_id != 4:
            raise Exception("BAD_LOGIC")
        self.status_id = 16  # status_id = ST_RUNNING
        logger.info("Started (status=%i)", self.status_id)

    def pause(self, symbol=None):
        if self.status_id & 224:
            # Completed/Aborted/Paused or goting to be
            logger.info("Pause rejected (error=%s, status=%i)", symbol,
                        self.status_id)

            if self.error_symbol is None:
                # Update error label only
                self.error_symbol = symbol
            return False

        nst = self.status_id | ST_PAUSED | 2
        logger.info("Pause (error=%s, status=%i -> %i)",
                    symbol, self.status_id, nst)
        self.status_id = nst
        self.error_symbol = symbol
        return True

    def paused(self):
        if self.status_id & 192:
            logger.error("PAUSED invoke at wrong status (status=%i)",
                         self.status_id)
            return

        nst = (self.status_id | ST_PAUSED) & ~2
        logger.info("Paused (status=%i -> %i)", self.status_id, nst)
        self.status_id = nst
        self.pause_timer()

    def resume(self):
        if self.status_id & 192:
            # Completed/Aborted or goting to be
            logger.error("Resume rejected (status=%i)", self.status_id)
            return False
        elif self.status_id & 34 == 32:
            # Paused
            nst = (self.status_id & ~ST_PAUSED) | 2
            logger.info("Resumimg (status=%i -> %i)", self.status_id, nst)
            self.status_id = nst
            self.error_symbol = None
            return True
        else:
            logger.error("Resume rejected (status=%i)", self.status_id)
            return False

    def resumed(self):
        if self.status_id & 192:
            logger.error("RESUMED invoke at wrong status (status=%i)",
                         self.status_id)
            return

        nst = (self.status_id & ~ST_PAUSED) & ~2
        logger.info("Resumed (status=%i -> %3i)", self.status_id, nst)
        self.status_id = nst
        self.start_timer()

    def abort(self, symbol=None):
        if self.status_id & 192:
            # Completed/Aborted or goting to be
            logger.info("Abort rejected (status=%i)", self.status_id)
            return False

        logger.info("Abort (error=%s, status=%i -> %i)",
                    symbol, self.status_id, ST_ABORTED)
        self.status_id = ST_ABORTED
        self.error_symbol = symbol
        self.pause_timer()
        self.terminate()

        if symbol:
            logger.warning("Close player directly because abort with "
                           "unexpected error")
            self.close()

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
            "session": self.session,
            "st_id": st_id,
            "st_label": self.macro.name if self.macro and st_id == 16
            else self.paused_macro.name if self.paused_macro and st_id == 48
            else STATUS_MSG.get(st_id, "UNKNOW_STATUS"),
            "error": self.error_symbol.args if self.error_symbol else [],
            "time_total": self.total_used_times,
            "time_running": self.used_times
        }

    def terminate(self):
        pass

    def close(self):
        pass
