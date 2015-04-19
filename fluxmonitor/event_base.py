
from errno import EINTR
import logging
import select

logger = logging.getLogger(__name__)


class EventBase(object):
    POLL_TIMEOUT = 5.0

    def __init__(self):
        self.rlist = []

    def add_read_event(self, fd_obj):
        self.rlist.append(fd_obj)

    def remove_read_event(self, fd_obj):
        if fd_obj in self.rlist:
            self.rlist.remove(fd_obj)
            return True
        else:
            return False

    def run(self):
        self.running = True

        while self.running:
            try:
                rlist, wlist, xlist = select.select(self.rlist,
                                                    (),
                                                    (),
                                                    self.POLL_TIMEOUT)
            except select.error as err:
                if err.args[0] == EINTR:
                    continue
                else:
                    raise

            for r in rlist:
                try:
                    r.on_read()
                except Exception:
                    logger.exception("Unhandle error")

            try:
                self.each_loop()
            except Exception:
                logger.exception("Unhandle error")