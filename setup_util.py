
from pkgutil import walk_packages
import ctypes.util
import platform
import sys

from fluxmonitor import VERSION as _VERSION


def get_version():
    return ".".join(_VERSION)


def get_packages():
    return [name
            for _, name, ispkg in walk_packages(".")
            if name.startswith("fluxmonitor") and ispkg]


def checklib(lib_name, package_name):
    if not ctypes.util.find_library(lib_name):
        sys.stderr.write("%s (%s) is not found\n" % (package_name, lib_name))
        sys.exit(1)


def is_test():
    return 'test' in sys.argv


def is_linux():
    return platform.system().lower().startswith("linux")


def setup_test():
    from fluxmonitor import config
    config.general_config["db"] = "./tmp/test_db"
    config.general_config["logfile"] = "./tmp/test_log"
    config.general_config["keylength"] = 512
    config.general_config["debug"] = True
    config.network_config["unixsocket"] = "./tmp/network-sock"
    config.uart_config["headboard"] = "./tmp/headboard-uart"
    config.uart_config["mainboard"] = "./tmp/mainboard-uart"
    config.uart_config["pc"] = "./tmp/pc-uart"
    config.robot["filepool"] = "./tmp/test_filepool"


def get_scripts():
    return ["bin/fluxnetworkd", "bin/fluxupnpd", "bin/fluxhal-uartd",
        "bin/fluxrobot"]

