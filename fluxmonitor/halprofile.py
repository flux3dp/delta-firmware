
from os.path import expanduser


MODEL_DARWIN_DEV = "darwin-dev"
MODEL_LINUX_DEV = "linux-dev"
MODEL_G1 = "model:1"

LINUX_PLATFORM = "linux"
DARWIN_PLATFORM = "darwin"


PROFILES = {
    MODEL_DARWIN_DEV: {
        "db": expanduser("~/.fluxmonitor_dev/db"),
        "gcode-pool": expanduser("~/.fluxmonitor_dev/filepool"),
        "scan_camera": 0,
    },
    MODEL_LINUX_DEV: {
        "db": expanduser("~/.fluxmonitor_dev/db"),
        "gcode-pool": expanduser("~/.fluxmonitor_dev/filepool"),
        "scan_camera": None,
    },
    MODEL_G1: {
        "db": "/var/db/fluxmonitord",
        "gcode-pool": "/var/gcode",
        "mainboard_uart":
            # "/dev/serial/by-path/platform-bcm2708_usb-usb-0:1.4:1.0",
            # TODO: /dev/ttyACM0 is a temp soluction for using USB hub
            "/dev/ttyACM0",
        "headboard_uart": "/dev/ttyAMA0",
        "pc_uart": None,
        "scan_camera": 0,
    }
}


def get_model_id():
    import platform as P

    if P.uname()[0] == "Darwin":
        return MODEL_DARWIN_DEV
    elif P.uname()[0] == "Linux":
        with open("/proc/cpuinfo", "r") as f:
            buf = f.read()
            # Need some method to check if it is raspberry A
            if "BCM2708" in buf or "BCM2835" in buf:
                return MODEL_G1
            else:
                return MODEL_LINUX_DEV
    else:
        raise Exception("Can not get model id")


def get_model_profile():
    return PROFILES.get(get_model_id())


def is_dev_model(profile=None):
    if profile is None:
        profile = get_model_id()

    return profile == MODEL_LINUX_DEV or profile == MODEL_DARWIN_DEV


def get_platform():
    import platform as _platform
    if _platform.system().lower().startswith("linux"):
        return LINUX_PLATFORM
    elif _platform.system().lower().startswith("darwin"):
        return DARWIN_PLATFORM
    else:
        raise Exception("Can not identify platform")


CURRENT_MODEL = get_model_id()
PLATFORM = get_platform()
