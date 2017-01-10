
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

network_services = {
    "wpa_supplicant": "/sbin/wpa_supplicant",
    "hostapd": "/usr/sbin/hostapd",
    "dhclient": "/sbin/dhclient",
    "dhcpd": "/usr/sbin/dhcpd"
}

uart_config = {
    "headboard": "/tmp/.headboard",
    "mainboard": "/tmp/.mainboard",
    "pc": "/tmp/.pc",

    "control": "/tmp/.halcontrol"
}


MAX_CORRECTION_ROUND = 10

DEVICE_POSITION_LIMIT = (172, 172, 212)

HEAD_POWER_TIMEOUT = 5

CONFIGURE_ENDPOINT = "/tmp/.configure"
MAINBOARD_ENDPOINT = "/tmp/.mainboard"
HEADBOARD_ENDPOINT = "/tmp/.headboard"
UART_ENDPOINT = "/tmp/.pc"
HALCONTROL_ENDPOINT = "/tmp/.halcontrol"

CAMERA_ENDPOINT = "/tmp/.camera"
ROBOT_ENDPOINT = "/tmp/.robot"
PLAY_ENDPOINT = "/tmp/.player"

SCAN_CAMERA_ID = None

NETWORK_MANAGE_ENDPOINT = "/tmp/.fluxmonitord-network"

PLAY_SWAP = "/tmp/autoplay.swap.fc"

FIRMWARE_UPDATE_PATH = "/var/autoupdate.fxfw"
USERSPACE = None


def load_model_profile():
    from fluxmonitor.halprofile import PROFILE
    import sys
    self = sys.modules[__name__]
    profile = PROFILE

    general_config["db"] = profile["db"]

    self.SCAN_CAMERA_ID = profile.get("scan_camera_id")
    self.USERSPACE = profile["userspace"]
    self.PLAY_SWAP = profile.get("playswap", self.PLAY_SWAP)
    self.FIRMWARE_UPDATE_PATH = profile.get("firmware_update_path",
                                            self.FIRMWARE_UPDATE_PATH)


load_model_profile()
