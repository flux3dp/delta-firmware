#!/usr/bin/env python

from tempfile import mkdtemp
from hashlib import sha256
from time import sleep
import pkg_resources
import argparse
import zipfile
import shutil
import json
import sys
import os

from serial import Serial, SerialException


# Note:
#   return 1: Error while updating
#   return 8/9: File broken
#
#

def unpack_resource(zf, metadata):
    name, signature = metadata

    zf.extract(name)

    chipertype, chipertext = signature.split(":")
    if chipertype == "sha256":
        chiper = sha256()
    else:
        raise RuntimeError("chiper error: %s" % chipertype)

    with open(name, "rb") as f:
        buf = f.read(4096)
        while buf:
            chiper.update(buf)
            buf = f.read(4096)
    if chiper.hexdigest() == chipertext:
        return name
    else:
        raise RuntimeError("chipertext error")


def fast_check(zf):
    mi = zf.getinfo("MANIFEST.in")
    if mi.file_size > 8*2**20:
        raise RuntimeError("MANIFEST.in size overlimit, ignore")
    mi = zf.getinfo("signature")
    if mi.file_size > 8*2**20:
        raise RuntimeError("signature size overlimit, ignore")


def validate_signature(manifest_fn, signature_fn):
    if os.path.exists("/etc/flux/fxupdate.pem"):
        keyfile = "/etc/flux/fxupdate.pem"
    else:
        keyfile = pkg_resources.resource_filename("fluxmonitor",
                                                  "data/fxupdate.pem")
    ret = os.system("openssl dgst -sha1 -verify %s -signature %s %s" % (
                    keyfile, signature_fn, manifest_fn))
    return ret == 0


def get_mainboard_tty():
    hwtree_lists = [
        "/sys/devices/platform/soc/20980000.usb/usb1/1-1/1-1.3/1-1.3:1.0/tty",
        "/sys/devices/platform/bcm2708_usb/usb1/1-1/1-1.3/1-1.3:1.0/tty"
    ]
    for hwtree in hwtree_lists:
        if os.path.exists(hwtree):
            ttyname = os.listdir(hwtree)[0]
            return os.path.join("/dev", ttyname)

    for i in range(10):
        if os.path.exists("/dev/ttyACM%s" % i):
            return "/dev/ttyACM%s" % i

    raise RuntimeError("Mainboard not found")


def update_mbfw(fw_path, tty):
    from RPi import GPIO

    GPIO_MAINBOARD_POW_PIN = 16
    GPIO_NOT_DEFINED = (22, 24, )
    MAINBOARD_ON = GPIO.HIGH
    MAINBOARD_OFF = GPIO.LOW
    GPIO.setmode(GPIO.BOARD)
    GPIO.setwarnings(False)

    try:
        for pin in GPIO_NOT_DEFINED:
            GPIO.setup(pin, GPIO.IN)
        GPIO.setup(GPIO_MAINBOARD_POW_PIN, GPIO.OUT, initial=MAINBOARD_OFF)

        sleep(0.5)
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)
        sleep(1.0)

        if os.system("stty -F %s 1200" % tty) != 0:
            raise RuntimeError("stty exec failed")

        sleep(3.0)

        if os.system("bossac -p %s -e -w -v -b %s" % (
                     tty.split("/")[-1], fw_path)) != 0:
            raise RuntimeError("bossac exec failed")

        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_OFF)
        sleep(0.5)
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)
        sleep(1.0)
    finally:
        GPIO.cleanup()


def main():
    parser = argparse.ArgumentParser(description='fluxmonitor updater')
    parser.add_argument('--dryrun', dest='dryrun', action='store_const',
                        const=True, default=False, help='Dry run')
    parser.add_argument('package_file', type=str,
                        help='Update package file')
    options = parser.parse_args()
    options.package_file = os.path.abspath(options.package_file)

    workdir = mkdtemp()
    try:
        extra_deb_tasks = None
        extra_eggs_tasks = None
        egg_task = None
        mbfw_task = None

        tty = get_mainboard_tty()
        s = Serial(port=tty, baudrate=115200, timeout=0)
        s.write("\nX5S85\n")

        try:
            with zipfile.ZipFile(options.package_file, "r") as zf:
                fast_check(zf)

                zf.extract("MANIFEST.in", workdir)
                zf.extract("signature", workdir)

                manifest_fn = os.path.join(workdir, "MANIFEST.in")
                signature_fn = os.path.join(workdir, "signature")
                if not validate_signature(manifest_fn, signature_fn):
                    print("Can not validate signature")
                    sys.exit(8)

                with open(manifest_fn, "r") as f:
                    manifest = json.load(f)
                os.chdir(workdir)

                extra_deb_tasks = [unpack_resource(zf, package) \
                                      for package in manifest["extra_deb"]]
                extra_eggs_tasks = [unpack_resource(zf, package) \
                                      for package in manifest["extra_eggs"]]
                egg_task = unpack_resource(zf, manifest["egg"])
                mbfw_task = unpack_resource(zf, manifest["mbfw"])

        except Exception:
            s.write("\nX5S0\n")
            sys.exit(9)

        s.close()

        if options.dryrun:
            return

        for package in extra_deb_tasks:
            if os.system("dpkg -i %s" % package) > 0:
                raise RuntimeError("Install %s failed" % package)

        for package in extra_eggs_tasks:
            if os.system("easy_install %s" % package) > 0:
                raise RuntimeError("Install %s failed" % package)

        if os.system("easy_install %s" % egg_task) > 0:
            raise RuntimeError("Install %s failed" % egg_task)

        update_mbfw(mbfw_task, tty)
    finally:
        shutil.rmtree(workdir)

if __name__ == "__main__":
    main()
