
from fluxmonitor.sys import nl80211

def set_wlan(ifname, ssid, network_type, wepkey=None, psk=None):
    nl80211.wlan_config(ifname=ifname, ssid=ssid, network_type=network_type,
        wepkey=wepkey, psk=psk)


def wlan_flameout(ifname):
    if ifname.startswith("wlan"):
        nl80211.wlan_down()
        nl80211.wlan_up()
    else:
        raise RuntimeError("There is no flameout SOP for device %s" % ifname)
