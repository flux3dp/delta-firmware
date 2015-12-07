
import logging

from fluxmonitor.err_codes import EXEC_CONVERGENCE_FAILED
from fluxmonitor.storage import Metadata
from fluxmonitor.misc import correction

logger = logging.getLogger(__name__)


def do_correction(meta, x, y, z):
    old_corr = meta.plate_correction
    new_corr = correction.calculate(
        old_corr["X"], old_corr["Y"], old_corr["Z"], old_corr["H"], x, y, z, 0)
    new_corr.pop("H")
    meta.plate_correction = new_corr

    logger.debug("Old correction: M666X%(X).4fY%(Y).4fZ%(Z).4f", old_corr)
    return "M666X%(X).4fY%(Y).4fZ%(Z).4f" % new_corr


class ZprobeMacro(object):
    def __init__(self, on_success_cb, on_error_cb, clean=False, ttl=20):
        self._on_success_cb = on_success_cb
        self._on_error_cb = on_error_cb
        self._clean = clean
        self.meta = Metadata()
        self.history = []
        self.ttl = ttl
        self.data = None

        self.convergence = False
        self.round = 0

    def on_command_empty(self, executor):
        if self.convergence:
            self._on_success_cb()
            return

        if self.data:
            data = self.data
            self.history.append(data)

            new_h = self.meta.plate_correction["H"] - data

            if abs(data) < 0.05:
                self.convergence = True
                executor.main_ctrl.send_cmd("G28", executor)
                return

            else:
                if self.round >= self.ttl:
                    executor.main_ctrl.send_cmd("G28", executor)
                    self._on_error_cb(EXEC_CONVERGENCE_FAILED)
                    return

                elif new_h > 245 or new_h < 239:
                    logger.error("Correction input failed: %s", data)

                else:
                    self.meta.plate_correction = {"H": new_h}
                    executor.main_ctrl.send_cmd("M666H%.4f" % new_h, executor)
                self.round += 1

        executor.main_ctrl.send_cmd("G30X0Y0", executor)

    def on_command_sendable(self, executor):
        pass

    def start(self, executor):
        if self._clean:
            self.meta.plate_correction = {"H": 242}
            executor.main_ctrl.send_cmd("M666H242", executor)
            executor.main_ctrl.send_cmd("G28", executor)
        else:
            self.on_command_empty(executor)

    def on_mainboard_message(self, msg, executor):
        if msg.startswith("Bed Z-Height at"):
            str_prope = msg.rsplit(" ", 1)[-1]
            self.data = float(str_prope)

    def on_headboard_message(self, msg, executor):
        pass

    def on_patrol(self, executor):
        pass
