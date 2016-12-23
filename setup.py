#!/usr/bin/env python

from setuptools import setup, Extension

from setup_utils import LD_TIME, PY_INCLUDES, DEFAULT_MACROS
import setup_utils


setup_utils.checklibs()

setup(
    name="fluxmonitor",
    version=setup_utils.VERSION,
    author="Flux Crop.",
    author_email="cerberus@flux3dp.com",
    description="",
    license="?",
    include_package_data=True,
    packages=setup_utils.get_packages(),
    test_suite="tests.main.everything",
    entry_points=setup_utils.ENTRY_POINTS,
    install_requires=setup_utils.get_install_requires(),
    tests_require=setup_utils.TEST_REQUIRE,
    setup_requires=['pytest-runner'],
    libraries=[
        ("flux_hal", {
            "sources": ["src/libflux_hal/halprofile.c"],
            "include_dirs": [],
            "macros": DEFAULT_MACROS
        }),
        ("flux_crypto", {
            "sources": [
                "src/libflux_crypto/flux_crypto_rsa.c",
                "src/libflux_crypto/flux_crypto_aes.c",
                "src/libflux_crypto/pbkdf2.c"],
            "include_dirs": PY_INCLUDES,
            "macros": DEFAULT_MACROS
        }),
        ("flux_identify", {
            "sources": [
                "src/libflux_identify/rescue.c",
                "src/libflux_identify/model_dev.c",
                "src/libflux_identify/model_rasp.c",
            ],
            "include_dirs": ["src"] + PY_INCLUDES,
            "macros": DEFAULT_MACROS
        })
    ],
    ext_modules=[
        Extension(
            'fluxmonitor.misc.systime', sources=[
                "src/systime/systime.c", ],
            extra_compile_args=["-std=c99"],
            define_macros=DEFAULT_MACROS,
            libraries=LD_TIME, extra_objects=[], include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.security._security', sources=[
                "src/security/security.c", ],
            extra_compile_args=["-std=c99"],
            define_macros=DEFAULT_MACROS,
            libraries=["crypto"], extra_objects=[], include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.player._device_fsm', sources=[
                "src/device_fsm/device_fsm.cpp",
                "src/device_fsm/fsm.cpp", ],
            language="c++",
            define_macros=DEFAULT_MACROS,
            libraries=[], extra_objects=[], include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.misc.correction', sources=[
                "src/correction/vector_3.cpp",
                "src/correction/main.cpp",
                "src/correction/correction.cpp"],
            language="c++",
            define_macros=DEFAULT_MACROS,
            libraries=[], extra_objects=[], include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.player._head_controller', sources=[
                "src/player/misc.c",
                "src/player/head_controller.c"],
            define_macros=DEFAULT_MACROS,
            libraries=LD_TIME, extra_objects=[], include_dirs=["src"]
        ),
        Extension(
            'fluxmonitor.player._main_controller', sources=[
                "src/player/misc.c",
                "src/player/main_controller_misc.c",
                "src/player/main_controller.c"],
            define_macros=DEFAULT_MACROS,
            libraries=LD_TIME, extra_objects=[], include_dirs=["src"]
        ),
        Extension("fluxmonitor.hal.camera._v4l2_camera", sources=[
            "src/v4l2_camera/v4l2_camera_module.cpp",
            "src/v4l2_camera/v4l2_camera.cpp"], language="c++"),
        Extension("fluxmonitor.hal._usbcable", sources=[
            "src/usbcable/usb_txrx.c",
            "src/usbcable/usbcable.c"],
            libraries=["usb-1.0"])
    ]
)
