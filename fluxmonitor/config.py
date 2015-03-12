
import tempfile
import json
import os

# The following is default config

network_config = {
    "unixsocket": os.path.join(tempfile.gettempdir(), ".fluxmonitor-wlan"),
    "wpa_supplicant": "/sbin/wpa_supplicant",
    "hostapd": "/usr/sbin/hostapd",
    "dhclient": "/sbin/dhclient",
    "dhcpd": "/usr/sbin/dhcpd"
}


def override_config(alt_config, current):
    for key, val in alt_config.items():
        current[key] = val


def load_config(filename):
    try:
        with open(filename, "r") as f:
            doc = json.load(f)

            override_config(doc.get("network_config", {}), network_config)

    except Exception as error:
        print(error)


def try_load_config():
    if os.path.exists("fluxmonitord.json"):
        load_config("fluxmonitord.json")
    elif os.path.exists(os.path.expanduser("~/.fluxmonitord.json")):
        load_config(os.path.expanduser("~/.fluxmonitord.json"))
    elif os.path.exists("/etc/fluxmonitord.json"):
        load_config("/etc/fluxmonitord.json")

try_load_config()
