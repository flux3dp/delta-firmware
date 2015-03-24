
import platform as _platform
import os as _os

develope_env = "armv6l" not in _platform.uname()

if _platform.system().lower().startswith("linux"):
    platform = "linux"
elif _platform.system().lower().startswith("darwin"):
    platform = "darwin"
else:
    raise "fluxmonitor can not run under %s" % _platform.system()


# The following is default config

general_config = {
    "db": "/var/db/fluxmonitord",
    "logfile": "fluxmonitord.log",
    "log_syntax": "[%(asctime)s,%(levelname)s,%(name)s] %(message)s",
    "log_timefmt": "%Y-%m-%d %H:%M:%S",
    "debug": True
}


network_config = {
    "unixsocket": "/tmp/.fluxmonitor-wlan",
    "wpa_supplicant": "/sbin/wpa_supplicant",
    "hostapd": "/usr/sbin/hostapd",
    "dhclient": "/sbin/dhclient",
    "dhcpd": "/usr/sbin/dhcpd"
}


serial_config = {
    "port": "/dev/ttyAMA0",
    "baudrate": 115200
}


def override_config(alt_config, current):
    for key, val in alt_config.items():
        current[key] = val


def load_config(filename):
    import json
    try:
        with open(filename, "r") as f:
            doc = json.load(f)

            override_config(doc.get("network_config", {}), network_config)
            override_config(doc.get("general_config", {}), general_config)
            override_config(doc.get("serial_config", {}), serial_config)
    except Exception as error:
        print(error)


def try_load_config():
    if _os.path.exists("fluxmonitord.json"):
        load_config("fluxmonitord.json")
    elif _os.path.exists(_os.path.expanduser("~/.fluxmonitord.json")):
        load_config(_os.path.expanduser("~/.fluxmonitord.json"))
    elif _os.path.exists("/etc/fluxmonitord.json"):
        load_config("/etc/fluxmonitord.json")

try_load_config()
