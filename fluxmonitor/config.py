
import tempfile
import os

wlan_config = {
    "unixsocket": os.path.join(tempfile.gettempdir(), ".fluxmonitor-wlan")
}