
def wpa_supplicant_config_str(config):
    security = config.get("security")
    if security == "":
        return """network={
            ssid="%(ssid)s"
            mode=0
            key_mgmt=NONE
}""" % config

    elif security == "WEP":
        return """network={
            ssid="%(ssid)s"
            mode=0
            wep_key0="%(wepkey)s"
            key_mgmt=NONE
}""" % config

    elif security in ["WPA-PSK", "WPA2-PSK"]:
        return """network={
            ssid="%(ssid)s"
            mode=0
            psk=%(psk)s
            proto=RSN
            key_mgmt=WPA-PSK
}""" % config

    else:
        raise RuntimeError("Uknow wireless security: " + security)


def wpa_supplicant_config_to_file(filepath, config):
    with open(filepath, "w") as f:
        f.write(wpa_supplicant_config_str(config))


def hostapd_config_str(ifname):
    return """# Create by fluxmonitord
interface=%(ifname)s
ssid=FLUX-3D-Printer
hw_mode=g
channel=5
""" % {"ifname": ifname}


def hostapd_config_to_file(filepath, ifname):
    with open(filepath, "w") as f:
        f.write(hostapd_config_str(ifname))
