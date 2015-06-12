
from pkgutil import walk_packages
import ctypes.util
import platform
import sys

from fluxmonitor import STR_VERSION


def get_install_requires():
    packages = ['setuptools', 'psutil', 'python-memcached', ]
    if is_linux():
        packages += ['pyroute2', 'RPi.GPIO']
    if is_darwin():
        packages += ['netifaces']
    return packages


def get_tests_require():
    return ['pycrypto']


def get_version():
    return STR_VERSION


def get_packages():
    return [name
            for _, name, ispkg in walk_packages(".")
            if name.startswith("fluxmonitor") and ispkg]


def checklibs():
    checklib('crypto', 'OpenSSL', )
    checklib('jpeg', 'libjpeg', )


def checklib(lib_name, package_name):
    if not ctypes.util.find_library(lib_name):
        sys.stderr.write("%s (%s) is not found\n" % (package_name, lib_name))
        sys.exit(1)


def is_test():
    return 'test' in sys.argv


def is_linux():
    return platform.system().lower().startswith("linux")


def is_darwin():
    return platform.system().lower().startswith("darwin")


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
    config.robot_config["filepool"] = "./tmp/test_filepool"


def get_entry_points():
    return {
        "console_scripts": [
            "fluxupnpd=fluxmonitor.bin.fluxupnpd:main",
            "fluxhal-uartd=fluxmonitor.bin.fluxuartd:main",
            "fluxnetworkd=fluxmonitor.bin.fluxnetworkd:main",
            "fluxusbd=fluxmonitor.bin.fluxusbd:main",

            "fluxrobot=fluxmonitor.bin.fluxrobot:main",

            "fluxinfo=fluxmonitor.bin.fluxinfo:main"
        ]
    }


def get_scripts():
    return []
