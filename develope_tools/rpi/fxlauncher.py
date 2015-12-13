#!/usr/bin/env python

import shutil
import sys
import os

filename = ''
factory_egg = '/home/pi/monitor_dist' + '/' + 'fluxmonitor-0.8a2-py2.7-linux-armv6l.egg'

USB_AUTOUPDATE_LOCATION = "/media/usb/autoupdate.fxfw"
AUTOUPDATE_LOCATION = "/var/autoupdate.fxfw"
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


def find_fxfw_from_usb():
    if os.path.exists(USB_AUTOUPDATE_LOCATION):
        if os.path.getsize(USB_AUTOUPDATE_LOCATION) < (100 * 2 ** 20):
            shutil.copyfile(USB_AUTOUPDATE_LOCATION,
                            AUTOUPDATE_LOCATION)


def bootstrap_autoupdate():
    try:
        find_fxfw_from_usb()
        if not os.path.exists(AUTOUPDATE_LOCATION):
            return

        ret = os.system("fxupdate.py %s" % AUTOUPDATE_LOCATION)
        if ret in (8, 9):
            os.unlink(AUTOUPDATE_LOCATION)
        else:
            raise UpdateError("Return %i" % ret)
    except UpdateError:
        raise
    except Exception:
        return


def start_service(force=True):
    from signal import SIGTERM
    from pkg_resources import load_entry_point
    from time import sleep, time

    for service, startup_params in SERVICE_LIST:
        ret = check_running(service)
        if force and ret:
            print >> sys.stderr, (service, 'is running, need to be killed')
            print >> sys.stderr, ('killing ' + service)
            os.kill(int(ret), SIGTERM)

            while check_running(service):
                print >> sys.stderr, ('wait %s to shutdown' % service)
                sleep(1)

            print >> sys.stderr, (service, 'really shutdown')

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
                    print >> sys.stderr, ('start %s success' % service)
                    break

                sleep(0.5)  # ?
                print >> sys.stderr, ('waiting %s start' % service)
                if time() - start_t > 10:
                    print >> sys.stderr, (service, 'starting timeout, not running')
                    success = False
                    break

    return pid


def check_running(service):
    import fcntl
    import errno
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


def update():
    for routine in [check_version, download_release, intall_release, reboot]:
        if routine():
            continue
        else:
            break


def check_version():
    global filename
    try:
        import urllib
        import urllib2
        from pkg_resources import parse_version, get_distribution

        print >> sys.stderr, ('getting release data')
        # TODO: change to real server
        url = 'http://www.csie.ntu.edu.tw/~b00902053/1'
        user_agent = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'
        values = {'name': 'Yen', 'location': 'Taiwan', 'language': 'Python'}
        headers = {'User-Agent': user_agent}

        data = urllib.urlencode(values)
        req = urllib2.Request(url, data, headers)
        response = urllib2.urlopen(req)
        release_version, filename = response.read().strip().split('\n')
    except:
        # no internet?
        print >> sys.stderr, ("can't get release data")
        return False
    else:
        current_version = get_distribution('fluxmonitor').version
        if parse_version(release_version) > parse_version(current_version):
            print >> sys.stderr, ('Need to update\n release: %s, installed: %s' % (release_version, current_version))
            return True
        else:
            print >> sys.stderr, ('No need to update\n release: %s, installed: %s' % (release_version, current_version))
            return False


def download_release():
    try:
        global filename
        print >> sys.stderr, ('try to download %s' % (filename))
        import urllib

        # TODO: change to proper user name
        dist_path = '/home/pi/monitor_dist'
        if not os.path.exists(dist_path):
            os.mkdir(dist_path)

        # TODO: change to real server
        urllib.urlretrieve("http://www.csie.ntu.edu.tw/~b00902053/" + filename, dist_path + '/' + filename)
        filename = dist_path + '/' + filename
        print >> sys.stderr, ('download success')
    except:
        return False
    else:
        return True


def intall_release():
    from subprocess import call
    _exit = call(['sudo', 'easy_install', filename])
    if _exit == 0:
        return True
    else:
        restore_factory()


def restore_factory():
    from subprocess import call
    from shutil import rmtree
    db_path = '/var/db/fluxmonitord/'
    rmtree(db_path)
    if not os.path.exists(db_path):
        os.mkdir(db_path)

    _exit = call(['sudo', 'easy_install', factory_egg])
    if _exit == 0:
        return True
    else:
        # TODO: proper email
        print >> sys.stderr, ('\033[91m' + 'Reinstall Factory Fail!!\nPlease contact to us via info@flux.com' + '\033[0m')
        raise


def reboot():
    os.system('sudo reboot')


def main():
    bootstrap_autoupdate()
    start_service()
    # TODO:
    # pid = start_service()
    # if pid != 0:  # parent run update routine
    #     update()


class UpdateError(Exception):
    pass


if __name__ == '__main__':
    main()
