
from pkg_resources import load_entry_point
from time import sleep, time
import argparse
import fcntl
import errno
import os


SERVICE_LIST = (
    # Syntax: (service entry name", ("service", "startup", "params"))
    ("fluxnetworkd", ('--pid', '/var/run/fluxnetworkd.pid',
                      '--log', '/var/log/fluxnetworkd.log', '--daemon')),
    ("fluxhald", ('--pid', '/var/run/fluxhald.pid',
                  '--log', '/var/log/fluxhald1.log', '--daemon')),
    ("fluxusbd", ('--pid', '/var/run/fluxusbd.pid',
                  '--log', '/var/log/fluxusbd.log', '--daemon')),
    ("fluxupnpd", ('--pid', '/var/run/fluxupnpd.pid',
                   '--log', '/var/log/fluxupnpd.log', '--daemon')),
    ("fluxrobotd", ('--pid', '/var/run/fluxrobotd.pid',
                    '--log', '/var/log/fluxrobotd.log', '--daemon')),
    ("fluxcamerad", ('--pid', '/var/run/fluxcamerad.pid',
                     '--log', '/var/log/fluxcamerad.log', '--daemon')),
)


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


def try_config_network(dryrun=False):
    anti_garbage_usb_mass_storage()
    if os.path.exists("/media/usb/config_flux.txt"):
        print("USB Disk found")

        from ConfigParser import RawConfigParser
        from fluxmonitor.security import get_serial
        from fluxmonitor.storage import Storage
        from hashlib import md5

        storage = Storage("general", "meta")
        with open("/media/usb/config_flux.txt") as f:
            h = md5(f.read()).hexdigest()
            print("Fingerprint local=%s, disk=%s" %
                  (storage["flashconfig_history"], h))

            if storage["flashconfig_history"] == h:
                print("This config file is already done, ignore")
                return

        c = RawConfigParser()
        c.read("/media/usb/config_flux.txt")

        if "device" in c.sections():
            device = dict(c.items("device"))
            s = device.get("serial")
            if s and get_serial() != s:
                print("Device serial not match")
                return
        else:
            print("Device section not found")
            return

        if "general" in c.sections():
            general_config = dict(c.items("general"))

            name = general_config.get("name")
            if name:
                if dryrun:
                    print("[Dryrun] Config name to: %s" % name)
                else:
                    from fluxmonitor.storage import Metadata
                    m = Metadata()
                    m.nickname = general_config["name"]

            password = general_config.get("password")
            if password:
                if dryrun:
                    print("[Dryrun] Set password to: ***")
                else:
                    from fluxmonitor.security import set_password
                    set_password(general_config["password"])

        if "network" in c.sections():
            network_config = dict(c.items("network"))

            if dryrun:
                print("[Dryrun] Config network: %s" % network_config)
            else:
                from fluxmonitor.misc import network_config_encoder as NCE  # noqa
                from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT
                import socket
                s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                s.connect(NETWORK_MANAGE_ENDPOINT)
                s.send(b"%s\x00%s" % (b"config_network",
                                      NCE.to_bytes(network_config)))

        storage["flashconfig_history"] = h


def init_rapi():
    if not os.path.exists("/var/gcode/userspace"):
        os.mkdir("/var/gcode/userspace")


def check_running(service):
    try:
        service_pic_file = '/var/run/' + service + '.pid'
        f = os.open(service_pic_file, os.O_RDONLY | os.O_WRONLY, 0o644)
        pid = open(service_pic_file, 'r').read()  # get process pid

        fcntl.lockf(f, fcntl.LOCK_NB | fcntl.LOCK_EX)

    except IOError as e:
        if e.args[0] == errno.EAGAIN:  # 11: can't get lock -> running
            return pid
        else:
            raise

    except OSError as e:
        if e.args[0] == errno.ENOENT:  # no such file -> not running
            return False
    else:
        'file exists but not locked?, shouldn\'t happened'
        return False


def main(params=None):
    parser = argparse.ArgumentParser(description='flux launcher')
    parser.add_argument('--dryrun', dest='dryrun', action='store_const',
                        const=True, default=False, help='Connect to smoothie')
    options = parser.parse_args(params)

    from fluxmonitor.halprofile import CURRENT_MODEL # noqa
    from fluxmonitor import security  # noqa # init security property

    try:
        if CURRENT_MODEL == 'delta-1':
            init_rapi()
    except Exception:
        pass

    for service, startup_params in SERVICE_LIST:
        ret = check_running(service)
        if ret:
            print('%s is already running\n' % service)
            continue

        if options.dryrun:
            print('[Dryrun] Start service: %s (%s)' % (service,
                                                       startup_params))
            continue

        pid = os.fork()
        if pid == 0:
            # child
            entry = load_entry_point('fluxmonitor', 'console_scripts', service)
            entry(startup_params)
            break
        else:
            # parent, check whether servie started
            start_t = time()
            while True:
                success = check_running(service)
                if success:
                    print('start %s success' % service)
                    break

                sleep(0.5)  # ?
                print('waiting %s start' % service)
                if time() - start_t > 10:
                    print('%s starting timeout, not running' % service)
                    success = False
                    break

    try_config_network(dryrun=options.dryrun)

if __name__ == "__main__":
    main()
