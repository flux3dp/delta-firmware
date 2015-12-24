
from fluxmonitor.config import USERSPACE
import os


def get_entry():
    return os.path.join(os.path.abspath(USERSPACE), "usb")
