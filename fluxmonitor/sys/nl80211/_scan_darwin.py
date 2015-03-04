
from subprocess import Popen, PIPE
import platform
import re

__all__ = ["scan"]

def parse_darwin_result(raw):
    for r in raw:
        m = re.search(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", r)

        if m:
            ssid = r[:m.start()].strip()
            d = re.split(r'\s+', r[m.start():].strip())
            yield {
                "ssid": ssid,
                "bssid": d[0],
                "rssi": d[1],
                "encrypt": d[5] != "NONE",
                "security": d[5] == "" if d[5] == "NONE" else d[5]
            }

def scan():
    proc = Popen([
        "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport",
        "-s"
    ], stdout=PIPE)
    proc.wait()

    results = proc.stdout.readlines()

    if proc.poll() != 0:
        raise RuntimeError("airport scan fail: %s " % proc.stderr.read(), proc.poll())

    return [r for r in parse_darwin_result(results)]

