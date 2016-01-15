
from ctypes import cdll
import distutils.sysconfig
import ctypes.util
import platform
import sys
import os

try:
    from setuptools import find_packages
except ImportError:
    raise RuntimeError("`setuptools` is required")

from fluxmonitor import __version__ as VERSION  # noqa


MODEL_DEFINES = {
    "linux-dev": "FLUX_MODEL_LINUX_DEV",
    "darwin-dev": "FLUX_MODEL_DARWIN_DEV",
    "delta-1": "FLUX_MODEL_D1"
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


def get_packages():
    return [p for p in find_packages() if p.startswith("fluxmonitor")]


DEFAULT_MACROS = []

HARDWARE_MODEL = None

TEST_REQUIRE = ['pytest', 'pycrypto']

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
        "fluxlauncher=fluxmonitor.bin.fluxlauncher:main",

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
            HARDWARE_MODEL = "delta-1"
            DEFAULT_MACROS += [("FLUX_MODEL_D1", 1)]
        else:
            HARDWARE_MODEL = "linux-dev"
            DEFAULT_MACROS += [("FLUX_MODEL_LINUX_DEV", 1)]


def get_install_requires():
    packages = ['setuptools', 'psutil', 'setproctitle', 'sysv_ipc', 'pyserial']

    if is_linux():
        packages += ['pyroute2']

    if is_darwin():
        packages += ['netifaces']

    if HARDWARE_MODEL == "delta-1":
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

LD_TIME = []

if is_linux():
    LD_TIME += ["rt"]
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
