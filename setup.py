#!/usr/bin/env python
from setuptools import setup, find_packages
import platform

VERSION = "0.0.1"

install_requires = ['setuptools', 'psutil', 'python-memcached']

if platform.system().lower().startswith("linux"):
    install_requires += ['pyroute2']

setup(
    name="fluxmonitor",
    version=VERSION,
    author="Flux Crop.",
    author_email="cerberus@flux3dp.com",
    description="",
    license="?",
    packages=find_packages(),
    test_suite="tests.main.everything",
    scripts=["bin/fluxmonitord", "bin/flux_wlan_scan",
        "bin/flux_network_config"],
    install_requires=install_requires,
)
