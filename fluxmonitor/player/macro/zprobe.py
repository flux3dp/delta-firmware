
from collections import deque
import logging

from fluxmonitor.err_codes import HARDWARE_ERROR, EXEC_CONVERGENCE_FAILED, \
    EXEC_ZPROBE_ERROR
from fluxmonitor.storage import Metadata
from .base import MacroBase

logger = logging.getLogger(__name__)


class ZprobeMacro(MacroBase):
    name = "CORRECTING"

    def __init__(self, on_success_cb, ttl=5, threshold=0.05, clean=True):
        self._on_success_cb = on_success_cb
        self._running = False
        self.meta = Metadata()
        self.threshold = threshold
        self.history = []
        self.ttl = ttl
        self.data = None
        self.clean = clean

        self.debug_logs = deque(maxlen=16)

        self.convergence = False
        self.round = 0

    def start(self, k):
        self._running = True
        if self.clean:
            self.meta.plate_correction = {"H": 242}
            k.mainboard.send_cmd("M666H242")
        k.mainboard.send_cmd("G30X0Y0")

    def giveup(self, k):
        if self._running:
            k.mainboard.send_cmd("G1F10392X0Y0Z220")
            self._running = False
            self.data = None
            return False
        else:
            return True

    def on_command_empty(self, k):
        if not self._running:
            return

        if self.convergence:
            self._on_success_cb()
            return

        if self.data:
            data = self.data
            self.history.append(data)

            new_h = self.meta.plate_correction["H"] - data

            if new_h > 244:
                logger.error("Correction input failed: %s", data)
            else:
                self.meta.plate_correction = {"H": new_h}
                corr_cmd = "M666H%.4f" % new_h
                k.mainboard.send_cmd(corr_cmd)
                logger.debug("Corr H: %s", corr_cmd)

            if abs(data) < self.threshold:
                self.convergence = True
                k.mainboard.send_cmd("G1F6000Z50")
                return

            elif self.round >= self.ttl:
                self.giveup(k)
                raise RuntimeError(HARDWARE_ERROR, EXEC_CONVERGENCE_FAILED)

        self.round += 1
        k.mainboard.send_cmd("G30X0Y0")
        self.data = None

    def on_ctrl_message(self, k, data):
        if data.startswith("DATA ZPROBE "):
            str_probe = data.rsplit(" ", 1)[-1]
            val = float(str_probe)
            if val <= -50:
                self.giveup(k)
                raise RuntimeError(HARDWARE_ERROR, EXEC_ZPROBE_ERROR)
            self.data = val
        elif data.startswith("DEBUG "):
            self.debug_logs.append(data[6:])
