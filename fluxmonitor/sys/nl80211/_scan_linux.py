
from subprocess import Popen, PIPE
import platform
import re

try:
    from io import StringIO
except ImportError:
    from StringIO import StringIO

__all__ = ["scan"]

def find_ssid(chunk):
    s = chunk.index("ESSID")
    e = chunk.index("\n", s + 2)
    if s < 0 or e < 0: return None
    else: return chunk[s + 8:e - 1]

def find_bssid(chunk):
    return chunk[:chunk.index("\n")].strip()

def find_rssi(chunk):
    s = chunk.index("Signal level")
    e = chunk.index(" ", s + 13)
    if s < 0 or e < 0: return None
    else: return chunk[s + 13:e]

def find_encrypt(chunk):
    s = chunk.index("Encryption key")
    e = chunk.index("\n", s + 2)
    if s < 0 or e < 0: return False
    else: return "on" in chunk[s + 14:e]

def find_security(chunk, has_enctype):
    if "WPA2" in chunk and "PSK" in chunk: return "WPA2-PSK"
    elif "WPA" in chunk and "PSK" in chunk: return "WPA-PSK"
    elif "WPA" in chunk and not "PSK" in chunk: return "ERROR"
    else: return "WEP"

def parse_iwlist_chunk_result(chunk):
    ssid = find_ssid(chunk)
    encrypt = find_encrypt(chunk)
    security = find_security(chunk, encrypt)

    if ssid and security != "ERROR":
        return {"ssid": ssid, "bssid": find_bssid(chunk),
            "rssi": find_rssi(chunk), "encrypt": encrypt,
            "security": security
        }

def scan():
    proc = Popen(["sudo", "-n", "iwlist", "scanning"], stdout=PIPE, stderr=PIPE)

    strbuffer = StringIO()
    while True:
        buf = proc.stdout.read(4096)
        if buf: strbuffer.write(buf.decode("utf8"))
        else: break

    # if proc.poll() != 0:
    #     raise RuntimeError("iwlist scan command fail: %s " % proc.stderr.read(), proc.poll())

    raw = strbuffer.getvalue()
    results = []

    last_anchor = -1
    for match in re.finditer("Cell [0-9]{2} - Address: ", raw):
        if last_anchor > 0:
            chunk = raw[last_anchor:match.start()]
            cell = parse_iwlist_chunk_result(chunk)
            if cell: results.append(cell)

        last_anchor = match.end()

    return results
