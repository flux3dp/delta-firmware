#!/usr/bin/env python

from setuptools import setup, Extension

import setup_util


setup_util.checklibs()

VERSION = setup_util.get_version()

install_requires = setup_util.get_install_requires()
tests_require = setup_util.get_tests_require()
packages = setup_util.get_packages()
entry_points = setup_util.get_entry_points()


if setup_util.is_test():
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
    entry_points=entry_points,
    install_requires=install_requires,
    tests_require=tests_require,
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
