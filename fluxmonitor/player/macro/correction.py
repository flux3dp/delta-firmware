
from collections import deque
import logging

from fluxmonitor.err_codes import HARDWARE_ERROR, EXEC_CONVERGENCE_FAILED, \
    EXEC_ZPROBE_ERROR
from fluxmonitor.storage import Preference
from fluxmonitor.misc import correction
from .startup import M666_TEMPLATE
from .base import MacroBase

logger = logging.getLogger(__name__)


def do_calibrate(pref, x, y, z):
    old_corr = pref.plate_correction
    new_corr = correction.calculate(
        old_corr["X"], old_corr["Y"], old_corr["Z"], old_corr["H"], x, y, z, 0,
        delta_radious=pref.plate_correction["R"])
    new_corr.pop("H")
    pref.plate_correction = new_corr

    calib_cmd = M666_TEMPLATE % pref.plate_correction
    logger.debug("Old correction: %s", calib_cmd)
    return calib_cmd


class CorrectionMacro(MacroBase):
    name = "CORRECTING"

    def __init__(self, on_success_cb, clean=False, ttl=6, threshold=0.05,
                 dist=None, correct_at_final=False):
        self._on_success_cb = on_success_cb
        self._clean = clean
        self._running = False
        self.correct_at_final = correct_at_final
        self.threshold = threshold
        self.zdist = dist
        self.pref = Preference.instance()
        self.history = []
        self.data = []
        self.ttl = ttl

        self.debug_logs = deque(maxlen=16)

        self.convergence = False
        self.round = 0

    def start(self, k):
        self._running = True
        self.round = 0

        zdist = self.zdist if self.zdist else self.pref.plate_correction["H"]
        if self._clean:
            self.pref.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": zdist}
        else:
            self.pref.plate_correction = {"H": zdist}

        k.mainboard.send_cmd(M666_TEMPLATE % self.pref.plate_correction)

    def giveup(self, k):
        if self._running:
            k.mainboard.send_cmd("G28+")
            self._running = False
            self.data = []
            return False
        else:
            return True

    def on_command_empty(self, k):
        if not self._running:
            return
        l = len(self.data)
        if l == 0:
            if self.round >= self.ttl:
                self.pref.plate_correction = {"X": 0, "Y": 0, "Z": 0, "H": 242}
                k.mainboard.send_cmd("M666X0Y0Z0H242")
                k.mainboard.send_cmd("G1F10392X0Y0Z230")
                k.mainboard.send_cmd("G28+")
                raise RuntimeError(HARDWARE_ERROR, EXEC_CONVERGENCE_FAILED)

            elif self.convergence:
                self._on_success_cb()

            else:
                logger.debug("Correction Round: %i", self.round)
                k.mainboard.send_cmd("G30X-73.6122Y-42.5")

        elif l == 1:
            k.mainboard.send_cmd("G30X73.6122Y-42.5")
        elif l == 2:
            k.mainboard.send_cmd("G30X0Y85")
        elif l == 3:
            self.history.append(self.data)
            data = self.data
            self.data = []

            dd = max(*data) - min(*data)
            if dd > 3:
                logger.error("Correction input failed: %s", data)
                # Re-run
                self.round += 1
                self.on_command_empty(k)
            elif dd < self.threshold:
                logger.info("Correction completed: %s", data)
                self.convergence = True

                if self.correct_at_final:
                    corr_str = do_calibrate(self.pref, *data)
                    logger.debug("Corr: %s", corr_str)
                    k.mainboard.send_cmd(corr_str)
                k.mainboard.send_cmd("G1F10392X0Y0Z30")

            else:
                corr_str = do_calibrate(self.pref, *data)
                logger.debug("New Correction: %s" % corr_str)
                k.mainboard.send_cmd(corr_str)
                self.round += 1

    def on_ctrl_message(self, k, data):
        if data.startswith("DATA ZPROBE "):
            str_probe = data.rsplit(" ", 1)[-1]
            val = float(str_probe)
            if val <= -50:
                self.giveup(k)
                raise RuntimeError(HARDWARE_ERROR, EXEC_ZPROBE_ERROR)

            self.data.append(val)
        elif data.startswith("DEBUG "):
            self.debug_logs.append(data[6:])
