
from fluxmonitor import halprofile

# The following is default config
general_config = {
    "db": "/var/db/fluxmonitord",
    "logfile": ".",
    "log_syntax": "[%(asctime)s,%(levelname)s,%(name)s] %(message)s",
    "log_timefmt": "%Y-%m-%d %H:%M:%S",
    "keylength": 1024,
    "debug": False
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
    "pc": "/tmp/.pc"
}


robot_config = {
    "filepool": "/media"
}


if halprofile.CURRENT_MODEL == halprofile.MODEL_DARWIN_DEV:
    import os
    general_config["db"] = os.path.join(os.path.expanduser("~"),
                                        ".fluxmonitor_dev", "db")
    robot_config["filepool"] = os.path.join(os.path.expanduser("~"),
                                            ".fluxmonitor_dev", "filepool")


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


def add_config_arguments(parser):
    parser.add_argument('-c', dest='configfile', type=str,
                        default='', help='PID file')


def load_config_arguments(options):
    if options.configfile:
        load_config(options.configfile)
