
import logging

from fluxmonitor.err_codes import HARDWARE_ERROR, EXEC_CONVERGENCE_FAILED, \
    EXEC_ZPROBE_ERROR
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


class CorrectionMacro(object):
    name = "CORRECTING"

    def __init__(self, on_success_cb, clean=False, ttl=6, threshold=0.05,
                 correct_at_final=False):
        self._on_success_cb = on_success_cb
        self._clean = clean
        self._running = False
        self.correct_at_final = correct_at_final
        self.threshold = threshold
        self.meta = Metadata()
        self.history = []
        self.data = []
        self.ttl = ttl

        self.convergence = False
        self.round = 0

    def on_command_empty(self, executor):
        if not self._running:
            return
        l = len(self.data)
        if l == 0:
            if self.round >= self.ttl:
                self.meta.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 242}
                executor.main_ctrl.send_cmd("M666X0Y0Z0H242", executor)
                executor.main_ctrl.send_cmd("G1F10000X0Y0Z230", executor)
                executor.main_ctrl.send_cmd("G28+", executor)
                raise RuntimeError(HARDWARE_ERROR, EXEC_CONVERGENCE_FAILED)

            elif self.convergence:
                self._on_success_cb()

            else:
                logger.debug("Correction Round: %i", self.round)
                executor.main_ctrl.send_cmd("G30X-73.6122Y-42.5", executor)

        elif l == 1:
            executor.main_ctrl.send_cmd("G30X73.6122Y-42.5", executor)
        elif l == 2:
            executor.main_ctrl.send_cmd("G30X0Y85", executor)
        elif l == 3:
            self.history.append(self.data)
            data = self.data
            self.data = []

            dd = max(*data) - min(*data)
            if dd > 3:
                logger.error("Correction input failed: %s", data)
                # Re-run
                self.round += 1
                self.on_command_empty(executor)
            elif dd < self.threshold:
                logger.info("Correction completed: %s", data)
                self.convergence = True

                if self.correct_at_final:
                    corr_str = do_correction(self.meta, *data)
                    executor.main_ctrl.send_cmd(corr_str, executor)
                executor.main_ctrl.send_cmd("G1F9000X0Y0Z30", executor)

            else:
                corr_str = do_correction(self.meta, *data)
                logger.debug("New Correction: %s" % corr_str)
                executor.main_ctrl.send_cmd(corr_str, executor)

                self.round += 1
                self.on_command_empty(executor)

    def on_command_sendable(self, executor):
        pass

    def start(self, executor):
        self._running = True
        self.round = 0
        if self._clean:
            self.meta.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 242}
            executor.main_ctrl.send_cmd("M666X0Y0Z0H242", executor)
        else:
            executor.main_ctrl.send_cmd("M666H242", executor)

    def giveup(self):
        self._running = False
        self.data = []

    def on_mainboard_message(self, msg, executor):
        if msg.startswith("Bed Z-Height at"):
            str_probe = msg.rsplit(" ", 1)[-1]
            val = float(str_probe)
            if val <= -50:
                # Clean fsr
                self.data = []
                executor.main_ctrl.send_cmd("G1F9000X0Y0Z230", executor)
                raise RuntimeError(HARDWARE_ERROR, EXEC_ZPROBE_ERROR)

            self.data.append(val)

    def on_headboard_message(self, msg, executor):
        pass

    def on_patrol(self, executor):
        pass
