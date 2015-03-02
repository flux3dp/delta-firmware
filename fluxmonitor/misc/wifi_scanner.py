
from subprocess import Popen, PIPE
import platform
import re

__all__ = ["scan_wifi"]

if platform.system().lower().startswith("linux"):
    def parse_wpa_cli_result(raw):
        for r in raw:
            r = r.strip()
            if re.match(r"^[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}", r):
                d = re.split(r'\s+', r)
                yield {
                    "ssid": d[-1],
                    "bssid": d[0],
                    "rssi": d[2],
                    "encrypt": d[3] != "[ESS]",
                    "security": d[3].replace("[ESS]", "")
                }

    def scan_wifi():
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

elif platform.system().lower().startswith("darwin"):
    def parse_darwin_result(row):
        d = re.split(r'\s+', row.strip())

        return {
            "ssid": d[0],
            "bssid": d[1],
            "rssi": d[2],
            "encrypt": d[6] != "NONE",
            "security": d[6] == "" if d[6] == "NONE" else d[6]
        }

    def scan_wifi():
        proc = Popen([
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport",
            "-s"
        ], stdout=PIPE)
        proc.wait()

        results = proc.stdout.readlines()

        if proc.poll() != 0:
            raise RuntimeError("airport scan fail: %s " % proc.stderr.read(), proc.poll())

        return [parse_darwin_result(r) for r in results]

else:
    def scan_wifi():
        raise RuntimeError("Wifi scann can not run on %s (not implement)" % platform.system(), 1)

