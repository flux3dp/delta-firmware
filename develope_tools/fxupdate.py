#!/usr/bin/env python

from tempfile import mkdtemp
from hashlib import sha256
from time import sleep
import pkg_resources
import argparse
import zipfile
import logging
import shutil
import json
import sys
import os

from serial import Serial

logger = logging.getLogger("FXUPDATE")
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(" ==> [%(levelname)s] %(message)s"))
logger.addHandler(handler)

# Note:
#   return 1: Error while updating
#   return 8/9: File broken
#
#


class DryrunSerial(object):
    def write(self, *args):
        pass

    def close(self):
        pass


def unpack_resource(zf, metadata):
    name, signature = metadata
    logger.debug("Unpack '%s' [signature=%s]", name, signature)

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
    if mi.file_size > 8 * 2**20:
        raise RuntimeError("MANIFEST.in size overlimit, ignore")
    mi = zf.getinfo("signature")
    if mi.file_size > 8 * 2**20:
        raise RuntimeError("signature size overlimit, ignore")


def validate_signature(options, manifest_fn, signature_fn):
    if os.path.exists(os.path.join(options.etc, "fxupdate.pem")):
        keyfile = os.path.join(options.etc, "fxupdate.pem")
    else:
        keyfile = pkg_resources.resource_filename("fluxmonitor",
                                                  "data/fxupdate.pem")
    logger.debug("Use keyfile: %s", keyfile)
    ret = os.system("openssl dgst -sha1 -verify %s -signature %s %s" % (
                    keyfile, signature_fn, manifest_fn))
    return ret == 0


def is_blocked_signature(options, signature_fn):
    with open(signature_fn, "rb") as f:
        fp = sha256(f.read()).hexdigest()
        return os.path.exists(os.path.join(options.etc, "blocked_fw", fp))


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

    GPIO_MAINBOARD_POW_PIN = 16  # noqa
    GPIO_NOT_DEFINED = (22, 24, )  # noqa
    MAINBOARD_ON = GPIO.HIGH  # noqa
    MAINBOARD_OFF = GPIO.LOW  # noqa
    GPIO.setmode(GPIO.BOARD)
    GPIO.setwarnings(False)

    try:
        for pin in GPIO_NOT_DEFINED:
            GPIO.setup(pin, GPIO.IN)
        GPIO.setup(GPIO_MAINBOARD_POW_PIN, GPIO.OUT, initial=MAINBOARD_OFF)

        sleep(0.5)
        GPIO.output(GPIO_MAINBOARD_POW_PIN, MAINBOARD_ON)
        sleep(1.0)

        cmd = "stty -F %s 1200" % tty
        logger.debug("EXEC '%s'", cmd)
        if os.system(cmd) != 0:
            raise RuntimeError("stty exec failed")

        sleep(3.0)

        cmd = "bossac -p %s -e -w -v -b %s" % (tty.split("/")[-1], fw_path)
        logger.debug("EXEC '%s'", cmd)
        if os.system(cmd) != 0:
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
    parser.add_argument('--etc', dest='etc', type=str, default='/etc/flux',
                        help='configure files location')
    parser.add_argument('--verbose', dest='verbose', action='store_const',
                        const=True, default=False,
                        help='Print more informations')

    options = parser.parse_args()
    options.package_file = os.path.abspath(options.package_file)
    if options.verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    workdir = mkdtemp()
    logger.debug("Configure directory: %s", options.etc)
    logger.debug("Working directory: %s", workdir)

    try:
        extra_deb_tasks = None
        extra_eggs_tasks = None
        egg_task = None
        mbfw_task = None

        preprocess_script = None
        postprocess_script = None

        if options.dryrun:
            logger.warn("Dry run")
            s = DryrunSerial()
            tty = None
        else:
            tty = get_mainboard_tty()
            logger.debug("Found mainboard at %s", tty)
            s = Serial(port=tty, baudrate=115200, timeout=0)
            s.write("\nX5S85\n")

        try:
            with zipfile.ZipFile(options.package_file, "r") as zf:
                fast_check(zf)

                zf.extract("MANIFEST.in", workdir)
                zf.extract("signature", workdir)

                manifest_fn = os.path.join(workdir, "MANIFEST.in")
                signature_fn = os.path.join(workdir, "signature")
                if not validate_signature(options, manifest_fn, signature_fn):
                    logger.error("Can not validate signature")
                    sys.exit(8)

                if is_blocked_signature(options, signature_fn):
                    logger.error("Signature is in block list")
                    sys.exit(8)

                with open(manifest_fn, "r") as f:
                    manifest = json.load(f)
                os.chdir(workdir)

                extra_deb_tasks = [unpack_resource(zf, package)
                                   for package in manifest["extra_deb"]]
                extra_eggs_tasks = [unpack_resource(zf, package)
                                    for package in manifest["extra_eggs"]]
                egg_task = unpack_resource(zf, manifest["egg"])

                if "preprocess" in manifest:
                    preprocess_script = unpack_resource(
                        zf, manifest["preprocess"])
                if "postprocess" in manifest:
                    postprocess_script = unpack_resource(
                        zf, manifest["postprocess"])

                mbfw_task = unpack_resource(zf, manifest["mbfw"])

        except Exception:
            logger.exception("Unknown error")
            s.write("\nX5S0\n")
            sys.exit(9)

        s.close()

        if preprocess_script:
            cmd = "python %s %s" % (preprocess_script, options.etc)
            logger.debug("EXEC '%s'", cmd)
            if not options.dryrun:
                if os.system(cmd) > 0:
                    raise RuntimeError("Exec pre-process script failed")

        for package in extra_deb_tasks:
            cmd = "dpkg --dry-run -i %s" % package \
                  if options.dryrun else \
                  "dpkg -i %s" % package
            logger.debug("EXEC '%s'", cmd)
            if os.system(cmd) > 0:
                raise RuntimeError("Install %s failed" % package)

        for package in extra_eggs_tasks:
            cmd = "easy_install --dry-run %s" % package \
                  if options.dryrun else \
                  "easy_install %s" % package
            logger.debug("EXEC '%s'", cmd)
            if os.system(cmd) > 0:
                raise RuntimeError("Install %s failed" % package)

        if options.dryrun:
            cmd = "easy_install --dry-run %s" % egg_task
        else:
            cmd = "easy_install %s" % egg_task
        logger.debug("EXEC '%s'", cmd)
        if os.system(cmd) > 0:
            raise RuntimeError("Install %s failed" % egg_task)

        if options.dryrun:
            logger.warn("Ignore update mbfw (dryrun)")
        else:
            update_mbfw(mbfw_task, tty)

        if postprocess_script:
            cmd = "python %s %s" % (postprocess_script, options.etc)
            logger.debug("EXEC '%s'", cmd)
            if not options.dryrun:
                if os.system(cmd) > 0:
                    raise RuntimeError("Exec post-process script failed")

    finally:
        shutil.rmtree(workdir)


if __name__ == "__main__":
    main()
