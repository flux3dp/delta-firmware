#!/usr/bin/env python

from time import sleep
import shutil
import sys
import os

from serial import Serial, SerialException


USB_AUTOUPDATE_LOCATION = "/media/usb/autoupdate.fxfw"
FACTORY_FW_LOCATION = "/etc/flux/factory.fxfw"
AUTOUPDATE_LOCATION = "/var/autoupdate.fxfw"


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


def should_reset_to_factory():
    try:
        tty = get_mainboard_tty()
        s = Serial(port=tty, baudrate=115200, timeout=1)
        s.write("X5\n")
        answer = s.readall()
        return "INFO: ST=U" in answer
    except Exception:
        return False


def anti_garbage_usb_mass_storage():
    try:
        if os.path.ismount(os.path.realpath("/media/usb")):
            return 0

        entry = "/sys/devices/platform/soc/20980000.usb/usb1/1-1/1-1.2"
        if not os.path.exists(entry):
            return 1

        filename = os.path.join(entry, "bDeviceClass")
        if not os.path.exists(filename):
            return 2
        with open(filename, "r") as f:
            if f.read().strip() != "00":
                return 2

        filename = os.path.join(entry, "1-1.2:1.0/bInterfaceClass")
        if not os.path.exists(filename):
            return 3
        with open(filename, "r") as f:
            if f.read().strip() != "08":
                return 3

        ttl = 0
        while not os.path.ismount(os.path.realpath("/media/usb")):
            sleep(0.1)
            if ttl > 200:
                return 4
            else:
                ttl += 1
        return 0
    except Exception as e:
        print(e)
        return -1


def find_fxfw_from_usb():
    anti_garbage_usb_mass_storage()
    if os.path.exists(USB_AUTOUPDATE_LOCATION):
        print("Update file is found form USB")
        if os.path.getsize(USB_AUTOUPDATE_LOCATION) < (100 * 2 ** 20):
            print("Copy update file from USB to disk")
            shutil.copyfile(USB_AUTOUPDATE_LOCATION,
                            AUTOUPDATE_LOCATION)
        else:
            print("Update file in USB is too large")


def execute_autoupdate(find_usb=True):
    try:
        if find_usb:
            find_fxfw_from_usb()

        if not os.path.exists(AUTOUPDATE_LOCATION):
            return

        print("Invoke fxupdate.py")
        ret = os.system("fxupdate.py %s" % AUTOUPDATE_LOCATION)
        if ret in (0, 8, 9):
            os.unlink(AUTOUPDATE_LOCATION)
        else:
            raise UpdateError("Return %i" % ret)
    except UpdateError:
        raise
    except Exception as e:
        print(e)
        return
    finally:
        os.system("sync")


def main():
    if should_reset_to_factory():
        print("Reset to factory")
        print("Delete settings")
        shutil.rmtree("/var/db/fluxmonitord", ignore_errors=True)
        shutil.copyfile(FACTORY_FW_LOCATION, AUTOUPDATE_LOCATION)
        execute_autoupdate(find_usb=False)
    else:
        execute_autoupdate()

    print("Invoke fluxlauncher")
    os.system("fluxlauncher")


class UpdateError(Exception):
    pass


if __name__ == '__main__':
    main()
