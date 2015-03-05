
from fluxmonitor.sys import nl80211

public_tasks = ["set_wlan"]

def set_wlan(options, ifname="wlan0"):
    nl80211.wlan_config(ifname=options.get("ifname", ifname),
        ssid=options.get("ssid"), network_type=options.get("network_type"),
        wepkey=options.get("wepkey"), psk=options.get("psk"))

def wlan_flameout(ifname):
    if ifname.startswith("wlan"):
        nl80211.wlan_down()
        nl80211.wlan_up()
    else:
        raise RuntimeError("There is no flameout SOP for device %s" % ifname)
