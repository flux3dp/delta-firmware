
import distutils.sysconfig
from pkgutil import walk_packages
from ctypes import cdll
import ctypes.util
import platform
import sys
import os

from fluxmonitor import __version__ as VERSION


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
    libname = ctypes.util.find_library(lib_name)
    if libname:
        return libname
    else:
        sys.stderr.write("=" * 80)
        sys.stderr.write("\n%s (%s) is not found\n" % (package_name, lib_name))
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
        "fluxhald=fluxmonitor.bin.fluxhald:main",
        "fluxnetworkd=fluxmonitor.bin.fluxnetworkd:main",
        "fluxusbd=fluxmonitor.bin.fluxusbd:main",
        "fluxplayer=fluxmonitor.bin.fluxplayer:main",
        "fluxcamerad=fluxmonitor.bin.fluxcamera:main",

        "fluxrobotd=fluxmonitor.bin.fluxrobot:main",

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
    packages = ['setuptools', 'psutil', 'setproctitle', 'sysv_ipc', ]

    if is_linux():
        packages += ['pyroute2']

    if is_darwin():
        packages += ['netifaces']

    if HARDWARE_MODEL == "model-1":
        packages += ['RPi.GPIO']

    libev_path = checklib("ev", "libev")
    libev = cdll.LoadLibrary(libev_path)
    if libev.ev_version_major() != 4:
        sys.stderr.write("=" * 80)
        sys.stderr.write("\nlibev comes with wrong version it should be 4.X\n")
        sys.exit(1)
    if libev.ev_version_minor() >= 15:
        packages += ['pyev']
    else:
        packages += ['pyev==0.8.1-4.04']

    return packages


if is_linux():
    if "CFLAGS" in os.environ:
        os.environ["CFLAGS"] += " -std=c99"
    else:
        os.environ["CFLAGS"] = "-std=c99"

if is_darwin():
    os.environ["ARCHFLAGS"] = "-arch x86_64"
    if "CXXFLAGS" in os.environ:
        os.environ["CXXFLAGS"] += " -std=c++11"
    else:
        os.environ["CXXFLAGS"] = "-std=c++11"
