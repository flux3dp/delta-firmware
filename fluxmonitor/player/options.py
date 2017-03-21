
from fluxmonitor.storage import Storage, Preference
from fluxmonitor.config import DEVICE_POSITION_LIMIT, DEFAULT_MOVEMENT_TEST

__all__ = ["Options"]
inf = float("INF")


def ensure_value(val, default, func=lambda x: x):
    return func(val) if val else default


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
    autoresume = False
    max_x = inf
    max_y = inf
    max_z = inf
    backlash_config = None
    plus_extrusion = None

    def __init__(self, taskloader=None, head=None):
        storage = Storage("general", "meta")

        if taskloader:
            self.__load_from_metadata__(taskloader.metadata)
        if head:
            self.head = head
        self.__load_form_local__(storage)

        if taskloader:
            self.config_backlash(storage, taskloader.metadata)
        else:
            self.config_backlash(storage)

        self.config_plus_extrusion(storage)

    def config_backlash(self, storage, task_metadata={}):
        c = storage["enable_backlash"]
        if not c:
            c = task_metadata.get("BACKLASH", "N")
        if c == "Y":
            self.backlash_config = Preference.instance().backlash
        else:
            self.backlash_config = {"A": 0, "B": 0, "C": 0}

    def config_plus_extrusion(self, storage, task_metadata={}):
        c = storage["plus_extrusion"]
        self.plus_extrusion = c == "Y"

    def __load_from_metadata__(self, task_metadata):
        self.head = task_metadata.get("HEAD_TYPE")
        if self.head:
            self.head = self.head.upper()
        self.correction = task_metadata.get("CORRECTION")
        self.filament_detect = task_metadata.get("FILAMENT_DETECT")

        self.head_error_level = parse_int(
            task_metadata.get("HEAD_ERROR_LEVEL"), None)

        self.max_x = parse_int(task_metadata.get("MAX_X"), inf)
        self.max_y = parse_int(task_metadata.get("MAX_Y"), inf)
        self.max_z = parse_int(task_metadata.get("MAX_Z"), inf)

    def __load_form_local__(self, storage):
        self.play_bufsize = 10

        self.correction = ensure_value(
            storage.readall("auto_correction"),
            self.correction or "A")

        self.filament_detect = ensure_value(
            storage.readall("filament_detect"),
            self.filament_detect or "Y")

        self.head_error_level = parse_int(
            storage.readall("head_error_level"),
            self.head_error_level or 4095)

        self.autoresume = storage["autoresume"] == "Y"

        self.movement_test = ensure_value(storage["movement_test"],
                                          DEFAULT_MOVEMENT_TEST,
                                          lambda v: v == "Y")

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

        try:
            self.zoffset = float(storage["zoffset"])
        except Exception:
            self.zoffset = 0

        self.zprobe_dist = ({"XL": 120, "L": 180, "M": 210}).get(
            storage["zprobe_dist"], 242)

    def __parse_int_from_meta__(self, key, default):
        pass
