#!/usr/bin/env python
from setuptools import setup, find_packages
import platform

from fluxmonitor import VERSION as _VERSION

VERSION = ".".join([str(i) for i in _VERSION])

install_requires = ['setuptools', 'psutil', 'python-memcached', 'pycrypto']

if platform.system().lower().startswith("linux"):
    install_requires += ['pyroute2', 'RPi.GPIO']

setup(
    name="fluxmonitor",
    version=VERSION,
    author="Flux Crop.",
    author_email="cerberus@flux3dp.com",
    description="",
    license="?",
    packages=find_packages(exclude=["tests", "tests.*"]),
    test_suite="tests.main.everything",
    scripts=["bin/fluxmonitord",
             "bin/flux_wlan_scan", "bin/flux_network_config"],
    install_requires=install_requires,
)
