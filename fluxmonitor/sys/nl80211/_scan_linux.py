
from subprocess import Popen, PIPE
import platform
import re

__all__ = ["scan"]

def parse_wpa_cli_result(raw):
    for r in raw:
        r = r.strip()
        if re.match(r"^[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}", r):
            d = re.split(r'\s+', r, 4)
            yield {
                "ssid": d[-1],
                "bssid": d[0],
                "rssi": d[2],
                "encrypt": d[3] != "[ESS]",
                "security": d[3].replace("[ESS]", "")
            }

def scan():
    proc = Popen(["sudo", "-n", "wpa_cli", "scan"], stdout=PIPE, stderr=PIPE)
    proc.wait()

    if proc.poll() != 0:
        raise RuntimeError("wpa_cli scan command fail: %s " % proc.stderr.read(), proc.poll())

    proc = Popen(["sudo", "-n", "wpa_cli", "scan_result"], stdout=PIPE, stderr=PIPE)
    proc.wait()
    results = proc.stdout.readlines()

    if proc.poll() != 0:
        raise RuntimeError("wpa_cli scan_result command fail: %s " % proc.stderr.read(), proc.poll())

    return [r for r in parse_wpa_cli_result(results)]

