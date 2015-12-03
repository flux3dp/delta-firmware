
LENGTH_OF_LONG_PRESS_TIME = 1.5
GAP_BETWEEN_DOUBLE_CLICK = 0.3
DEBUG = False

# The following is default config
general_config = {
    "debug": False,

    "db": "/var/db/fluxmonitord",
    "keylength": 1024,

    "log_syntax": "[%(asctime)s,%(levelname)s,%(name)s] %(message)s",
    "log_timefmt": "%Y-%m-%d %H:%M:%S",
}

hal_config = {
    "mainboard_uart": None,
    "headboard_uart": None,
    "pc_uart": None,
    "scan_camera": None,
}

network_config = {
    "unixsocket": "/tmp/.fluxmonitord-network",
    "wpa_supplicant": "/sbin/wpa_supplicant",
    "hostapd": "/usr/sbin/hostapd",
    "dhclient": "/sbin/dhclient",
    "dhcpd": "/usr/sbin/dhcpd"
}


uart_config = {
    "headboard": "/tmp/.headboard",
    "mainboard": "/tmp/.mainboard",
    "pc": "/tmp/.pc",

    "control": "/tmp/.uart-control"
}

DEVICE_POSITION_LIMIT = (170, 170, 190)

MAINBOARD_RETRY_TTL = 10
HEADBOARD_RETRY_TTL = 5

HEADBOARD_ENDPOINT = "/tmp/.headboard"
MAINBOARD_ENDPOING = "/tmp/.mainboard"

CAMERA_ENDPOINT = "/tmp/.camera"

PLAY_ENDPOINT = "/tmp/.player"


robot_config = {
    "filepool": "/media"
}


def load_model_profile():
    from fluxmonitor.halprofile import get_model_profile
    profile = get_model_profile()

    general_config["db"] = profile["db"]
    general_config["scan_camera"] = profile["scan_camera"]

    hal_config["mainboard_uart"] = profile.get("mainboard_uart")
    hal_config["headboard_uart"] = profile.get("headboard_uart")
    hal_config["pc_uart"] = profile.get("pc_uart")
    hal_config["scan_camera"] = profile.get("scan_camera")

    robot_config["filepool"] = profile["gcode-pool"]


def override_config(alt_config, current):
    for key, val in alt_config.items():
        current[key] = val


def load_config(filename):
    import json
    with open(filename, "r") as f:
        doc = json.load(f)

        override_config(doc.get("network_config", {}), network_config)
        override_config(doc.get("general_config", {}), general_config)
        override_config(doc.get("uart_config", {}), uart_config)
        override_config(doc.get("robot_config", {}), robot_config)

load_model_profile()
