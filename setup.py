#!/usr/bin/env python

from setuptools import setup, Extension

import setup_utils


setup_utils.checklibs()

if setup_utils.is_test():
    setup_utils.setup_test()


setup(
    name="fluxmonitor",
    version=setup_utils.VERSION,
    author="Flux Crop.",
    author_email="cerberus@flux3dp.com",
    description="",
    license="?",
    packages=setup_utils.get_packages(),
    test_suite="tests.main.everything",
    entry_points=setup_utils.ENTRY_POINTS,
    install_requires=setup_utils.get_install_requires(),
    tests_require=setup_utils.TEST_REQUIRE,
    libraries=[
        ("flux_hal", {
            "sources": ["src/libflux_hal/halprofile.c"],
            "include_dirs": [],
            "macros": setup_utils.DEFAULT_MACROS
        }),
        ("flux_crypto", {
            "sources": [
                "src/libflux_crypto/flux_crypto_rsa.c",
                "src/libflux_crypto/flux_crypto_aes.c"],
            "include_dirs": setup_utils.PY_INCLUDES,
            "macros": setup_utils.DEFAULT_MACROS
        }),
        ("flux_identify", {
            "sources": [
                "src/libflux_identify/rescue.c",
                "src/libflux_identify/model_dev.c",
                "src/libflux_identify/model_rasp.c",
            ],
            "include_dirs": ["src"] + setup_utils.PY_INCLUDES,
            "macros": setup_utils.DEFAULT_MACROS
        })
    ],
    ext_modules=[
        Extension(
            'fluxmonitor._halprofile', sources=[
                "src/halprofile/halprofile.c"],
            extra_compile_args=["-std=c99"],
            define_macros=setup_utils.DEFAULT_MACROS,
            include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.security._security', sources=[
                "src/security/security.c", ],
            extra_compile_args=["-std=c99"],
            define_macros=setup_utils.DEFAULT_MACROS,
            libraries=["crypto"], extra_objects=[], include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.code_executor._device_fsm', sources=[
                "src/device_fsm/device_fsm.cpp",
                "src/device_fsm/fsm.cpp", ],
            language="c++",
            extra_compile_args=["-std=c++11"],
            define_macros=setup_utils.DEFAULT_MACROS,
            libraries=[], extra_objects=[], include_dirs=["src"]
        )
    ]
)
