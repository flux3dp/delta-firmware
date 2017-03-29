
from sys import maxint

from fluxmonitor.storage import Storage
from fluxmonitor.config import (DEFAULT_MOVEMENT_TEST, DEFAULT_H, LIMIT_MAX_R)
from fluxmonitor.player import macro as macros

__all__ = ["Options"]
inf = float("INF")


def ensure_value(val, default, func=lambda x: x):
    return func(val) if val else default


def parse_float(val, default):
    if val:
        try:
            return float(val)
        except Exception:
            pass
    return default


def parse_int(val, default):
    if val:
        try:
            return int(val, 10)
        except Exception:
            pass
    return default


class PlayerOptions(object):
    head = None
    correction = None
    head_error_level = None
    play_bufsize = 10
    filament_detect = None
    autoresume = False
    max_z = inf
    max_r = inf
    enable_backlash = False
    plus_extrusion = None

    def __init__(self, taskloader=None, head=None):
        storage = Storage("general", "meta")
        metadata = taskloader.metadata if taskloader else {}

        self._setup_toolhead(head, metadata)
        self._setup_leveling(storage, metadata)
        self._setup_filament_detect(storage, metadata)
        self._setup_toolhead_error_level(storage, metadata)
        self._setup_backlash(storage, metadata)
        self._setup_max_xyzr(metadata)
        self._setup_common(storage)

        # ALL DIRTY THINGS START FROM HERE
        # TODO: enable hardware error for toolhead pwm issue
        self.head_error_level |= 64

        if self.head != "EXTRUDER":
            # Only EXTRUDER need filament detect
            self.filament_detect = False
            # Only EXTRUDER allowed correction
            self.correction = "N"

    def _setup_toolhead(self, head, metadata):
        if head:
            self.head = head.upper()
        elif metadata and "HEAD_TYPE" in metadata:
            self.head = metadata["HEAD_TYPE"].upper()
        else:
            self.head = "EXTRUDER"

    def _setup_leveling(self, storage, metadata):
        device_setting = storage["auto_correction"]
        if device_setting:
            self.correction = device_setting
        else:
            self.correction = metadata.get("CORRECTION", "Y")

    def _setup_toolhead_error_level(self, storage, metadata):
        device_setting = storage["head_error_level"]
        if device_setting:
            self.head_error_level = parse_int(device_setting, maxint)
        else:
            self.head_error_level = parse_int(metadata.get("HEAD_ERROR_LEVEL"),
                                              maxint)

    def _setup_filament_detect(self, storage, metadata):
        device_setting = storage["filament_detect"]
        if device_setting:
            self.filament_detect = device_setting == "Y"
        else:
            self.filament_detect = metadata.get("FILAMENT_DETECT", "Y") == "Y"

    def _setup_max_xyzr(self, metadata):
        self.max_z = parse_float(metadata.get("MAX_Z"), inf)
        self.max_r = parse_float(metadata.get("MAX_R"), inf)
        self.max_r = min(self.max_r, LIMIT_MAX_R)

    def _setup_common(self, storage):
        self.autoresume = storage["autoresume"] == "Y"
        self.plus_extrusion = storage["plus_extrusion"] == "Y"
        self.movement_test = ensure_value(storage["movement_test"],
                                          DEFAULT_MOVEMENT_TEST,
                                          lambda v: v == "Y")
        self.zoffset = parse_float(storage["zoffset"], 0)

        zdist = parse_int(storage["zprobe_dist"], DEFAULT_H - 16)
        self.zprobe_dist = min(max(zdist, DEFAULT_H - 100), DEFAULT_H - 16)

    def _setup_backlash(self, storage, metadata):
        device_setting = storage["enable_backlash"]
        if device_setting:
            self.enable_backlash = device_setting == "Y"
        else:
            self.enable_backlash = metadata.get("BACKLASH", "N") == "Y"

    def get_player_initialize_macros(self):
        tasks = []
        tasks.append(macros.StartupMacro(None, options=self))
        if self.movement_test:
            tasks.append(macros.RunCircleMacro(None))
        if self.correction in ("A", "H"):
            if self.head == "EXTRUDER":
                tasks.append(macros.ControlHeaterMacro(None, 0, 170))
            if self.correction == "A":
                tasks.append(macros.ZprobeMacro(None, threshold=float("inf"),
                                                dist=self.zprobe_dist))
                tasks.append(macros.CorrectionMacro(None))
            tasks.append(macros.ZprobeMacro(None, zoffset=self.zoffset))
        return tasks


Options = PlayerOptions
