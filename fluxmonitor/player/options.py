
from fluxmonitor.storage import Storage
from fluxmonitor.config import DEVICE_POSITION_LIMIT

__all__ = ["Options"]
inf = float("INF")


def ensure_value(val, default):
    return val if val else default


def parse_int(val, default):
    if val:
        try:
            return int(val, 10)
        except Exception:
            pass
    return default


class Options(object):
    head = None
    correction = None
    head_error_level = None
    play_bufsize = None
    filament_detect = None
    max_x = inf
    max_y = inf
    max_z = inf

    def __init__(self, taskloader=None):
        if taskloader:
            self.__load_from_metadata__(taskloader.metadata)
        self.__load_form_local__()

    def __load_from_metadata__(self, metadata):
        self.head = metadata.get("HEAD_TYPE")
        if self.head:
            self.head = self.head.upper()
        self.correction = metadata.get("CORRECTION")
        self.filament_detect = metadata.get("FILAMENT_DETECT")

        self.head_error_level = parse_int(
            metadata.get("HEAD_ERROR_LEVEL"), None)

        self.max_x = parse_int(metadata.get("MAX_X"), inf)
        self.max_y = parse_int(metadata.get("MAX_Y"), inf)
        self.max_z = parse_int(metadata.get("MAX_Z"), inf)

    def __load_form_local__(self):
        self.play_bufsize = 10

        storage = Storage("general", "meta")
        if self.correction is None:
            self.correction = ensure_value(
                storage.readall("auto_correction"), "H")

        if self.filament_detect is None:
            self.filament_detect = ensure_value(
                storage.readall("filament_detect"), "Y")

        if self.head_error_level is None:
            self.head_error_level = parse_int(
                storage.readall("head_error_level"), 4095)

        if self.head != "EXTRUDER":
            # Only EXTRUDER need filament detect
            self.filament_detect = "N"
            # Only EXTRUDER allowed correction
            self.correction = "N"

        # TODO: enable hardware error for toolhead pwm issue
        self.head_error_level |= 64
        self.max_x = min(self.max_x, DEVICE_POSITION_LIMIT[0])
        self.max_y = min(self.max_y, DEVICE_POSITION_LIMIT[1])
        self.max_z = min(self.max_z, DEVICE_POSITION_LIMIT[2])

    def __parse_int_from_meta__(self, key, default):
        pass
