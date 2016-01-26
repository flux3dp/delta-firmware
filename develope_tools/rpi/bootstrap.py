#!/usr/bin/env python

# This script can build a fluxmonitor from a clean raspbian
#
# RELEASE NOTIFY
# This script is write base on raspberry pi image: "RASPBIAN JESSIE LITE"
# release at 2015-11-21
#
# write by Cerberus
#
# REQUIRE FILES:
#  "bossac" - Atmel firmware tool, ask somebody to get it
#  "factory.fxfw" - fluxmonitor firmware package, ask someone to get it
#  "hostapd-rtl8188cus" - Wifi driver, find it in NAS
#  "wpa_supplicant-rtl8188cus" - Wifi driver, find it in NAS
#  "fxupdate.py" - Can be found at up directory
#  "fxconfig_network.py" - Can be found at up directory
#  "fxpasswd.py" - Can be found at up directory


import logging.config
import shutil
import sys
import os

if __name__ == "__main__":
    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'default': {
                'format': "%(levelname)s -> %(message)s"
            }
        },
        'handlers': {
            'console': {
                'level': 'INFO',
                'formatter': 'default',
                'class': 'logging.StreamHandler', }
        },
        'root': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True
        }
    })

logger = logging.getLogger()


def action_wrapper(fn):
    def wrap(*args, **kw):
        try:
            fn(*args, **kw)
        except Exception:
            logger.exception("Error occour")
            sys.stdout.write("Continue? (y/N)")
            resp = sys.stdin.readline()
            if resp.strip().lower() != "y":
                sys.exit(1)
    return wrap


def system(cmd):
    logger.info("Run: %s", cmd)
    if os.system(cmd) > 0:
        raise RuntimeError("Subtask return error")


@action_wrapper
def close_wifi_power_management():
    logger.info("Write wifi power management setting to "
                "/etc/modprobe.d/8192cu.conf")
    with open("/etc/modprobe.d/8192cu.conf", "w") as f:
        f.write("options 8192cu rtw_power_mgnt=0")


@action_wrapper
def update_and_install_system_package():
    system("sudo apt-get update")
    system("sudo apt-get install python-opencv usbmount isc-dhcp-server")


@action_wrapper
def turn_off_useless_services():
    services = ["avahi-daemon", "dbus", "triggerhappy", "dhcpcd", "ssh",
                "isc-dhcp-server", "networking", "alsa-state.service",
                "alsa-store.service", "alsa-restore.service"]
    for s in services:
        system("sudo update-rc.d -f %s remove" % s)
        system("sudo systemctl disable %s.service")

    system("sudo systemctl disable dbus.socket")


@action_wrapper
def copy_wifi_userlevel_driver():
    logger.info("Copy hostapd and wpa_supplicant to system")
    shutil.copyfile("hostapd-rtl8188cus",
                    "/usr/sbin/hostapd")
    system("chmod 555 /usr/sbin/hostapd")
    shutil.copyfile("wpa_supplicant-rtl8188cus",
                    "/usr/bin/wpa_supplicant")
    system("chmod 555 /usr/bin/wpa_supplicant")


@action_wrapper
def copy_mainboard_firmware_tool():
    logger.info("Copy bossac to system")
    shutil.copyfile("bossac", "/usr/bin/bossac")
    system("chmod 555 /usr/bin/bossac")


@action_wrapper
def install_pip():
    if os.path.exists("get-pip.py"):
        os.unlink("get-pip.py")
    system("wget https://bootstrap.pypa.io/get-pip.py")
    system("sudo python2.7 get-pip.py")


@action_wrapper
def remove_current_network_setting():
    logger.info("Clear /etc/network/interfaces")
    with open("/etc/network/interfaces", "w") as f:
        f.write("auto lo\n")
        f.write("iface lo inet loopback\n\n")
    logger.info("Clear /etc/wpa_supplicant/wpa_supplicant.conf")
    with open("/etc/wpa_supplicant/wpa_supplicant.conf", "w") as f:
        f.write("/etc/wpa_supplicant/wpa_supplicant.conf\n")
        f.write("update_config=1\n\n")


@action_wrapper
def install_python_package():
    packages = ["psutil", "setproctitle", "sysv_ipc", "pyserial"]
    for p in packages:
        system("pip install %s" % p)


@action_wrapper
def copy_standlone_py_script():
    for s in ["fxupdate.py", "fxconfig_network.py", "fxpasswd.py",
              "fxlauncher.py"]:
        system("cp %s /usr/bin/%s" % (s, s))
        system("chmod 555 /usr/bin/%s" % s)


@action_wrapper
def set_system_console():
    logger.info("Disable AMA0 system console")
    system("sudo systemctl stop serial-getty@ttyAMA0.service")
    system("sudo systemctl disable serial-getty@ttyAMA0.service")


@action_wrapper
def install_fluxmonitor():
    if not os.path.exists("/etc/flux"):
        os.mkdir("/etc/flux")
    logger.info("Copy fxupdate.pem to /etc/flux")
    shutil.copyfile("fxupdate.pem", "/etc/flux/fxupdate.pem")

    logger.info("Copy factory.fxfw to /etc/flux")
    shutil.copyfile("factory.fxfw", "/etc/flux/factory.fxfw")

    system("fxupdate.py factory.fxfw")


if __name__ == "__main__":
    close_wifi_power_management()
    update_and_install_system_package()
    turn_off_useless_services()
    copy_wifi_userlevel_driver()
    copy_mainboard_firmware_tool()
    install_pip()
    copy_standlone_py_script()
    install_python_package()
    install_fluxmonitor()
    set_system_console()
    remove_current_network_setting()

    print("Bootstrap completed.")
    sys.stdout.write("Reboot? (Y/n)")
    resp = sys.stdin.readline()
    if resp.strip().lower() != "n":
        system("sudo reboot")
