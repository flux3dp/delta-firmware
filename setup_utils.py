
import distutils.sysconfig
from pkgutil import walk_packages
import ctypes.util
import platform
import sys
import os

from fluxmonitor import STR_VERSION as VERSION


MODEL_DEFINES = {
    "linux-dev": "FLUX_MODEL_LINUX_DEV",
    "darwin-dev": "FLUX_MODEL_DARWIN_DEV",
    "model-1": "FLUX_MODEL_G1"
}


def is_test():
    return 'test' in sys.argv


def is_linux():
    return platform.system().lower().startswith("linux")


def is_darwin():
    return platform.system().lower().startswith("darwin")


def checklibs():
    checklib('crypto', 'OpenSSL', )
    checklib('jpeg', 'libjpeg', )


def checklib(lib_name, package_name):
    if not ctypes.util.find_library(lib_name):
        sys.stderr.write("%s (%s) is not found\n" % (package_name, lib_name))
        sys.exit(1)


def setup_test():
    from tempfile import mkdtemp
    tempbase = mkdtemp()

    from fluxmonitor import config
    config.general_config["db"] = os.path.join(tempbase, "db")
    config.general_config["keylength"] = 512
    config.general_config["debug"] = True
    config.network_config["unixsocket"] = os.path.join(tempbase, "network-us")
    config.uart_config["headboard"] = os.path.join(tempbase, "headboard-us")
    config.uart_config["mainboard"] = os.path.join(tempbase, "mainboard-us")
    config.uart_config["pc"] = os.path.join(tempbase, "pc-us")
    config.robot_config["filepool"] = os.path.join(tempbase, "filepool")

    import logging.config
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'default': {
                'format': "[%(asctime)s,%(levelname)s,%(name)s] %(message)s",
                'datefmt': "%Y-%m-%d %H:%M:%S"
            }
        },
        'handlers': {
            'file': {
                'formatter': 'default',
                'class': 'logging.FileHandler',
                'filename': "./tmp/test.log"
            }
        },
        'root': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True
        }
    })

    def on_exit():
        import shutil
        shutil.rmtree(tempbase)
    import atexit
    atexit.register(on_exit)


def get_packages():
    return [name
            for _, name, ispkg in walk_packages(".")
            if name.startswith("fluxmonitor") and ispkg]


DEFAULT_MACROS = []

HARDWARE_MODEL = None

TEST_REQUIRE = ['pycrypto']

PY_INCLUDES = [distutils.sysconfig.get_python_inc()]

ENTRY_POINTS = {
    "console_scripts": [
        "fluxupnpd=fluxmonitor.bin.fluxupnpd:main",
        "fluxhal-uartd=fluxmonitor.bin.fluxhald:main",  # Remove in next ver
        "fluxhald=fluxmonitor.bin.fluxhald:main",
        "fluxnetworkd=fluxmonitor.bin.fluxnetworkd:main",
        "fluxusbd=fluxmonitor.bin.fluxusbd:main",

        "fluxrobot=fluxmonitor.bin.fluxrobot:main",

        "fluxinit=fluxmonitor.bin.fluxinit:main"
    ]
}


if "FLUX_MODEL" in os.environ:
    define = MODEL_DEFINES.get(os.environ["FLUX_MODEL"])
    if not define:
        raise RuntimeError("Get unupport type in FLUX_MODEL env")

    DEFAULT_MACROS.append((define, 1))
    HARDWARE_MODEL = os.environ["FLUX_MODEL"]

elif is_darwin():
    DEFAULT_MACROS += [("FLUX_MODEL_DARWIN_DEV", 1)]
    HARDWARE_MODEL = "darwin-dev"

elif is_linux():
    with open("/proc/cpuinfo", "r") as f:
        buf = f.read()
        # TODO: Need some method to check if it is raspberry A
        if "BCM2708" in buf or "BCM2835" in buf:
            HARDWARE_MODEL = "model-1"
            DEFAULT_MACROS += [("FLUX_MODEL_G1", 1)]
        else:
            HARDWARE_MODEL = "linux-dev"
            DEFAULT_MACROS += [("FLUX_MODEL_LINUX_DEV", 1)]


def get_install_requires():
    packages = ['setuptools', 'psutil', 'setproctitle', 'python-memcached', ]
    if is_linux():
        packages += ['pyroute2']

    if is_darwin():
        packages += ['netifaces']

    if HARDWARE_MODEL == "model-1":
        packages += ['RPi.GPIO']

    return packages


if is_linux():
    if "CFLAGS" in os.environ:
        os.environ["CFLAGS"] += " -std=c99"
    else:
        os.environ["CFLAGS"] = "-std=c99"

if is_darwin():
    os.environ["ARCHFLAGS"] = "-arch x86_64"

    # if "CXXFLAGS" in os.environ:
    #     os.environ["CXXFLAGS"] += " -std=c++11"
    # else:
    #     os.environ["CXXFLAGS"] = "-std=c++11"
