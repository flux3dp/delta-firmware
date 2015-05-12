#!/usr/bin/env python

from setuptools import setup, Extension
from pkgutil import walk_packages

import setup_util

VERSION = setup_util.get_version()


# Process install_requires
install_requires = ['setuptools', 'psutil', 'python-memcached']

if setup_util.is_linux():
    install_requires += ['pyroute2', 'RPi.GPIO']
else:
    install_requires += ['netifaces']


# Process libraries
libraries = ['crypto']

setup_util.checklib('crypto', 'OpenSSL')


# Process packages
packages = setup_util.get_packages()


# Process scripts
scripts = setup_util.get_scripts()


if setup_util.is_test():
    install_requires += ['pycrypto']
    setup_util.setup_test()


setup(
    name="fluxmonitor",
    version=VERSION,
    author="Flux Crop.",
    author_email="cerberus@flux3dp.com",
    description="",
    license="?",
    packages=packages,
    test_suite="tests.main.everything",
    scripts=scripts,
    install_requires=install_requires,
    ext_modules=[
        Extension(
            'fluxmonitor.misc._security', sources=[
                "src/misc/security.c",
                "src/misc/openssl_bridge.c"],
            extra_compile_args=["-std=c99"],
            libraries=["crypto"],
            extra_objects=[], include_dirs=[])
    ]
)
