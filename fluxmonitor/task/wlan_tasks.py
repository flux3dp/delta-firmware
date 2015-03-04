
from fluxmonitor.sys import nl80211

tasks = ["set_wlan"]

def set_wlan(options):
    nl80211.wlan_config(options)

