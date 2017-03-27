
from os.path import expanduser
from fluxmonitor.security.identify import get_model_id, get_platform

MODEL_DARWIN_DEV = "darwin-dev"
MODEL_LINUX_DEV = "linux-dev"
MODEL_D1 = "delta-1"
MODEL_D1P = "delta-1p"

LINUX_PLATFORM = "linux"
DARWIN_PLATFORM = "darwin"


PROFILES = {
    MODEL_DARWIN_DEV: {
        "db": expanduser("~/.fluxmonitor_dev/db"),
        "userspace": expanduser("~/.fluxmonitor_dev/filepool"),
        "firmware_update_path": expanduser("~/.fluxmonitor_dev/update.fxfw"),
        "playswap": "/tmp/autoplay.fc",
        "scan_camera_id": 0,
    },
    MODEL_LINUX_DEV: {
        "db": expanduser("~/.fluxmonitor_dev/db"),
        "userspace": expanduser("~/.fluxmonitor_dev/filepool"),
        "firmware_update_path": expanduser("~/.fluxmonitor_dev/update.fxfw"),
        "playswap": "/tmp/autoplay.fc",
        "scan_camera_id": None,
    },
    MODEL_D1: {
        "db": "/var/db/fluxmonitord",
        "userspace": "/var/gcode/userspace",
        "playswap": "var/gcode/autoplay.fc",
        "mainboard_uart":
            # "/dev/serial/by-path/platform-bcm2708_usb-usb-0:1.4:1.0",
            # TODO: /dev/ttyACM0 is a temp soluction for using USB hub
            "/dev/ttyACM0",
        "headboard_uart": "/dev/ttyAMA0",
        "pc_uart": None,
        "max_r": 87,
        "default_h": 226,
        "default_r": 96.70,
        "default_movement_test": False,
        "scan_camera_id": 0,
        "scan_camera_model": 1,
    },
    MODEL_D1P: {
        "db": "/var/db/fluxmonitord",
        "userspace": "/var/gcode/userspace",
        "playswap": "var/gcode/autoplay.fc",
        "mainboard_uart":
            # "/dev/serial/by-path/platform-bcm2708_usb-usb-0:1.4:1.0",
            # TODO: /dev/ttyACM0 is a temp soluction for using USB hub
            "/dev/ttyACM0",
        "headboard_uart": "/dev/ttyAMA0",
        "pc_uart": None,
        "max_r": 87,
        "default_h": 226,
        "default_r": 96.20,
        "default_movement_test": True,
        "scan_camera_id": 0,
        "scan_camera_model": 2,
    },
}

CURRENT_MODEL = get_model_id()
PLATFORM = get_platform()
PROFILE = PROFILES[get_model_id()]
