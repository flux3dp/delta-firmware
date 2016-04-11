

try:
    unicode
except NameError:
    unicode = str

# """
# Config basic struct:
# {
#     "ifname": "wlan0",            # A valied linux NIC name
#     "method": "dhcp"|"static",    #
#
#     # Required only if mode set to static
#     "ipaddr": "192.168.1.2",      # A valid ipv4 address for interface
#     "mask": 24,                   # Network mask, only accept INT
#     "route": "192.168.1.1",       # Gateway ip address
#     "ns": "168.95.1.1",           # A valid DNS ipaddress (ipv4)
#
#     # Required only if NIC is a wireless device
#     "wifi_mode": "host"|"client"  # host is AP mode
#     "ssid": "YOUR_SSID",          #
#
#     # Required only if wifi has a security configuration
#     "security": "WEP"|"WPA-PSK"|"WPA2-PSK",
#
#     # Required only if wifi security set to "WEP"
#     "wepkey": "WEP_PASSWORD_HERE",
#
#     # Required only if wifi security set to "WPA-PSK" or "WPA2-PSK"
#     "psk": "WPA_PASSWORD_HERE"    # Password should not match to
#                                   # /^[0-9a-f]{64}$/
# }
# """


def parse_bytes(buf):
    raw_options = dict([i.split(b"=", 1) for i in buf.split(b"\x00")])
    return validate_options(raw_options)


def to_bytes(options):
    keyvalues = []

    for key, val in options.items():
        if isinstance(val, list):
            str_val = ",".join(val)
            keyvalues.append("%s=%s" % (key, str_val))
        elif val is None:
            continue
        elif key == "mask":
            keyvalues.append("%s=%i" % (key, val))
        else:
            keyvalues.append("%s=%s" % (key, val))
    return "\x00".join(keyvalues)


def validate_options(orig):
    options = {}

    if b"ifname" in orig:
        options["ifname"] = _b2s(orig[b"ifname"])

    method = orig.get(b"method")
    if method == b"dhcp":
        options["method"] = "dhcp"
    elif method == b"static":
        ons = orig[b"ns"]
        if not isinstance(ons, list):
            ns = _b2s(orig[b"ns"]).split(",")
        else:
            ns = ons

        options.update({
            "method": "static", "ipaddr": _b2s(orig["ipaddr"]),
            "mask": int(orig["mask"]),
            "route": _b2s(orig.get("route")),
            "ns": ns
        })
    elif method == b"internal":
        pass
    else:
        raise KeyError("method")

    if b"ssid" in orig:
        ssid = _b2s(orig[b"ssid"])
        wifi_mode = _b2s(orig.get(b"wifi_mode", b"client"))
        security = _b2s(orig.get(b"security"))

        if not ssid:
            raise KeyError("ssid")

        if wifi_mode not in ("client", "host"):
            raise KeyError("wifi_mode")
        if security not in ('WPA-PSK', 'WPA2-PSK', 'WEP', None):
            raise KeyError("security")

        options["ssid"] = ssid
        options["wifi_mode"] = wifi_mode
        options["security"] = security

        if security == "WEP":
            if wifi_mode == "host":
                raise KeyError("security")
            options["wepkey"] = _b2s(orig[b"wepkey"])
        elif security in ['WPA-PSK', 'WPA2-PSK']:
            options["psk"] = _b2s(orig[b"psk"])

        if wifi_mode == "host":
            options["method"] = "internal"

    return options


def _b2s(input):
    if input is None:
        return None
    elif isinstance(input, bytes):
        return input.decode("ascii", "ignore")
    elif isinstance(input, (unicode, str)):
        return input
    else:
        raise TypeError(input, input.__class__)
