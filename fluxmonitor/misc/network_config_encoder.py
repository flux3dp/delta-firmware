

def parse_bytes(buf):
    raw_opts = dict([i.split(b"=", 1) for i in buf.split(b"\x00")])
    options = {}

    if b"ifname" in raw_opts:
        options["ifname"] = _b2s(raw_opts[b"ifname"])

    method = raw_opts.get(b"method")
    if method == b"dhcp":
        options["method"] = "dhcp"
    elif method == b"static":
        options.update({
            "method": "static", "ipaddr": _b2s(raw_opts["ipaddr"]),
            "mask": int(raw_opts["mask"]),
            "route": _b2s(raw_opts.get("route")),
            "ns": _b2s(raw_opts[b"ns"]).split(",")
        })
    else:
        raise KeyError("method")

    if b"ssid" in raw_opts:
        ssid = _b2s(raw_opts[b"ssid"])
        wifi_mode = _b2s(raw_opts.get(b"wifi_mode", b"client"))
        security = _b2s(raw_opts.get(b"security"))

        if not ssid:
            raise KeyError("ssid")

        if wifi_mode not in ("client", "host"):
            raise KeyError("wifi_mode")
        if security not in ('WPA-PSK', 'WPA2-PSK', None):
            raise KeyError("security")

        options["ssid"] = ssid
        options["wifi_mode"] = wifi_mode
        options["security"] = security

        if security == "WEP":
            options["wepkey"] = _b2s(raw_opts[b"wepkey"])
        elif security in ['WPA-PSK', 'WPA2-PSK']:
            options["psk"] = _b2s(raw_opts[b"psk"])

    return options


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


def _b2s(bytes):
    if bytes is None:
        return None
    else:
        return bytes.decode("ascii", "ignore")
