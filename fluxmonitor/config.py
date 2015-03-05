
import tempfile
import os

network_config = {
    "unixsocket": os.path.join(tempfile.gettempdir(), ".fluxmonitor-wlan")
}