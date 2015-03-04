
from fluxmonitor.sys import nl80211

public_tasks = ["set_wlan"]

def set_wlan(options):
    nl80211.wlan_config(options)

def wlan_flameout(ifname):
    if ifname.startswith("wlan"):
        nl80211.wlan_down()
        nl80211.wlan_up()
    else:
        raise RuntimeError("There is no flameout SOP for device %s" % ifname)
