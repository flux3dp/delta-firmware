
from subprocess import Popen, PIPE
from time import sleep
import re

try:
    from io import StringIO
except ImportError:
    from StringIO import StringIO

__all__ = ["scan"]


def find_ssid(chunk):
    s = chunk.index("ESSID")
    e = chunk.index("\n", s + 2)
    if s < 0 or e < 0:
        return None
    else:
        return chunk[s + 7:e - 1]


def find_bssid(chunk):
    return chunk[:chunk.index("\n")].strip()


def find_rssi(chunk):
    s = chunk.index("Signal level")
    e = chunk.index(" ", s + 13)
    if s < 0 or e < 0:
        return None
    else:
        try:
            val = chunk[s + 13:e].split("/")[0]
            return int(val, 10) * -1
        except Exception:
            return None


def find_encrypt(chunk):
    s = chunk.index("Encryption key")
    e = chunk.index("\n", s + 2)
    if s < 0 or e < 0:
        return False
    else:
        return "on" in chunk[s + 14:e]


def find_security(chunk, has_enctype):
    if "WPA2" in chunk and "PSK" in chunk:
        return "WPA2-PSK"
    elif "WPA" in chunk and "PSK" in chunk:
        return "WPA-PSK"
    elif "WPA" in chunk and "PSK" not in chunk:
        return "ERROR"
    else:
        return "WEP"


def parse_iwlist_chunk_result(chunk):
    try:
        ssid = find_ssid(chunk)
        encrypt = find_encrypt(chunk)
        security = find_security(chunk, encrypt)

        if ssid and security != "ERROR":
            return {"ssid": ssid, "bssid": find_bssid(chunk),
                    "rssi": find_rssi(chunk), "encrypt": encrypt,
                    "security": security}
    except Exception:
        return None


def scan(ifname="wlan0"):
    proc = Popen(["iwlist", ifname, "scanning"],
                 stdout=PIPE, stderr=PIPE)

    strbuffer = StringIO()
    while True:
        buf = proc.stdout.read(4096)
        if buf:
            strbuffer.write(buf.decode("utf8"))
        else:
            break

    raw = strbuffer.getvalue()
    results = []

    last_anchor = -1
    for match in re.finditer("Cell [0-9]{2} - Address: ", raw):
        # Output from 0 to first match result is iwlist header, ignore it
        if last_anchor > 0:
            chunk = raw[last_anchor:match.start()]
            cell = parse_iwlist_chunk_result(chunk)
            if cell:
                results.append(cell)

        last_anchor = match.end()

    if last_anchor > 0:
        # Handle last match result to end of raw
        chunk = raw[last_anchor:]
        cell = parse_iwlist_chunk_result(chunk)
        if cell:
            results.append(cell)

    for i in range(6):
        ret = proc.poll()
        if ret is None:
            sleep(0.05)
        elif ret == 0:
            return results
        else:
            raise RuntimeError("HARDWARE_FAILURE")

    try:
        proc.kill()
    except Exception:
        pass

    raise RuntimeError("HARDWARE_FAILURE", "NO_RESPONSE")
