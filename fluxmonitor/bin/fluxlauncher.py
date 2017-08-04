
from pkg_resources import load_entry_point, resource_string
from signal import SIGTERM, SIGKILL
from time import sleep
import argparse
import fcntl
import errno
import sys
import os

LOG_ROOT = '/var/db/fluxmonitord/run/'
PID_FLUXNETWORKD = '/var/run/fluxnetworkd.pid'
PID_FLUXHALD = '/var/run/fluxhald.pid'
PID_FLUXUSBD = '/var/run/fluxusbd.pid'
PID_FLUXUPNPD = '/var/run/fluxupnpd.pid'
PID_FLUXROBOTD = '/var/run/fluxrobotd.pid'
PID_FLUXCAMERAD = '/var/run/fluxcamerad.pid'
PID_FLUXCLOUDD = '/var/run/fluxcloudd.pid'


PID_LIST = (
    PID_FLUXNETWORKD,
    PID_FLUXHALD,
    PID_FLUXUSBD,
    PID_FLUXUPNPD,
    PID_FLUXROBOTD,
    PID_FLUXCAMERAD,
    PID_FLUXCLOUDD
)

SERVICE_LIST = (
    # Syntax: (service entry name", ("service", "startup", "params"), pid file)
    ("fluxnetworkd", ('--log', LOG_ROOT + 'fluxnetworkd.log', '--daemon'),
     PID_FLUXNETWORKD),
    ("fluxhald", ('--log', LOG_ROOT + 'fluxhald.log', '--daemon'),
     PID_FLUXHALD),
    ("fluxusbd", ('--log', LOG_ROOT + 'fluxusbd.log', '--daemon'),
     PID_FLUXUSBD),
    ("fluxupnpd", ('--log', LOG_ROOT + 'fluxupnpd.log', '--daemon'),
     PID_FLUXUPNPD),
    ("fluxcamerad", ('--log', LOG_ROOT + 'fluxcamerad.log', '--daemon'),
     PID_FLUXCAMERAD),
    ("fluxrobotd", ('--log', LOG_ROOT + 'fluxrobotd.log', '--daemon'),
     PID_FLUXROBOTD),
    ("fluxcloudd", ('--log', LOG_ROOT + 'fluxcloudd.log', '--daemon'),
     PID_FLUXCLOUDD),
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
            print("Device section not found, ignore")

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
    if not os.path.exists("/var/db/fluxmonitord"):
        os.mkdir("/var/db/fluxmonitord")
    if not os.path.exists("/var/db/fluxmonitord/run"):
        os.mkdir("/var/db/fluxmonitord/run")

    if not os.path.exists("/var/db/fluxmonitord/boot_ver") or \
            open("/var/db/fluxmonitord/boot_ver").read() != "4":

        udev = resource_string("fluxmonitor", "data/rapi/udev-99-flux.rules")
        with open("/etc/udev/rules.d/99-flux.rules", "w") as f:
            f.write(udev)
        fxupdate = resource_string("fluxmonitor", "data/rapi/fxupdate.pysource")  # noqa
        with open("/usr/bin/fxupdate.py", "w") as f:
            f.write(fxupdate)
        fxlauncher = resource_string("fluxmonitor", "data/rapi/fxlauncher.pysource")  # noqa
        with open("/usr/bin/fxlauncher.py", "w") as f:
            f.write(fxlauncher)
        open("/var/db/fluxmonitord/boot_ver", "w").write("3")
        os.system("udevadm control --reload")
        os.system("sync")

        # Resolve log issue
        rsyslog = resource_string("fluxmonitor", "data/rapi/rsyslog.conf")
        with open("/etc/logrotate.d/rsyslog", "w") as f:
            f.write(rsyslog)
        if os.path.exists("/etc/cron.daily/logrotate"):
            os.system("mv /etc/cron.daily/logrotate /etc/cron.hourly")
        os.system("sync")
        os.system("/etc/cron.hourly/logrotate")

        # Resolve wifi driver issue
        with open("/etc/modprobe.d/8192cu.conf", "w") as f:
            f.write("""
options 8192cu rtw_power_mgnt=0
options r8188eu rtw_power_mgnt=0
options 8188eu rtw_power_mgnt=0
""")

        r8188 = "/lib/modules/4.1.13+/kernel/drivers/staging/rtl8188eu/8188eu.ko"
        if os.path.exists(r8188) and os.path.getsize(r8188) is not 1305956L:
            os.system("rmmod 8188eu")
            r8188bin = resource_string("fluxmonitor", "data/rapi/8188eu.ko")
            with open(r8188, "wb") as f:
                f.write(r8188bin)
            os.system("modprobe 8188eu")


def check_running(pidfile):
    try:
        f = os.open(pidfile, os.O_RDONLY | os.O_WRONLY, 0o644)
        pid = open(pidfile, 'r').read()  # get process pid
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


def terminate_proc(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return

    try:
        os.kill(pid, SIGTERM)
        for i in range(50):
            os.kill(pid, 0)
            sleep(0.2)
    except OSError:
        return

    try:
        os.kill(pid, SIGKILL)
    except OSError:
        return


def launch_proc(service, startup_params, pidfile, debug_mode):
    if os.path.exists(pidfile):
        os.unlink(pidfile)

    pid = os.fork()
    if pid == 0:
        # child
        entry = load_entry_point('fluxmonitor', 'console_scripts', service)
        try:
            if debug_mode:
                entry(startup_params + ("--debug", ))
            else:
                entry(startup_params)
        except Exception:
            sys.exit(1)
        sys.exit(1)
    else:
        while True:
            try:
                rpid, code = os.waitpid(pid, os.P_NOWAIT)
                if rpid:
                    print('start %s with %i' % (service, code))
                    return code
                else:
                    continue
            except OSError:
                print('waiting %s start' % service)
            sleep(0.1)


def main(params=None):
    parser = argparse.ArgumentParser(description='flux launcher')
    parser.add_argument('--dryrun', dest='dryrun', action='store_const',
                        const=True, default=False, help='Connect to smoothie')
    parser.add_argument('--update', dest='update', action='store_const',
                        const=True, default=False,
                        help='Stop all process and invoke fxlauncher for '
                             'upgrade')

    options = parser.parse_args(params)

    from fluxmonitor.halprofile import CURRENT_MODEL # noqa
    from fluxmonitor import security  # noqa # init security property
    from fluxmonitor import __version__

    try:
        if CURRENT_MODEL in ('delta-1', 'delta-1p'):
            init_rapi()
    except Exception as e:
        print(e)

    for pidfile in PID_LIST:
        try:
            if os.path.exists(pidfile):
                with open(pidfile) as f:
                    pidstr = f.read()
                    if pidstr.isdigit():
                        pid = int(pidstr)
                        if pid != os.getpid():
                            terminate_proc(pid)

                        if os.path.exists(pidfile):
                            os.unlink(pidfile)
        except Exception as e:
            print(repr(e))

    if options.update:
        for i in range(3, 1024):
            try:
                os.close(i)
            except Exception:
                pass

        os.execl("/usr/bin/python2.7", "python2.7", "/usr/bin/fxlauncher.py")

    debug_mode = "a" in __version__
    if debug_mode is False:
        try:
            open("/etc/flux/debug")
            debug_mode = True
        except Exception:
            pass

    import fluxmonitor.interfaces.handler  # noqa
    import fluxmonitor.interfaces.listener  # noqa

    for service, startup_params, pidfile in SERVICE_LIST:
        startup_params = startup_params + ("--pid", pidfile)
        if options.dryrun:
            print('[Dryrun] Start service: %s (%s)' % (service,
                                                       startup_params))
            continue

        ttl = 3
        while ttl and launch_proc(service, startup_params, pidfile, debug_mode) > 0:
            sleep(1)
            ttl -= 1

    try_config_network(dryrun=options.dryrun)

if __name__ == "__main__":
    main()
