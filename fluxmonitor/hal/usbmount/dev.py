
from fluxmonitor.config import robot_config
import os


def get_entry():
    return os.path.join(os.path.abspath(robot_config["filepool"]), "usb")
