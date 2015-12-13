
from pkg_resources import load_entry_point
from time import sleep, time
from signal import SIGTERM
import argparse
import fcntl
import errno
import sys
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
    options = parser.parse_args(params)

    for service, startup_params in SERVICE_LIST:
        ret = check_running(service)
        if ret:
            print('%s is already running\n' % service)
            continue
        # if force and ret:
        #     print >> sys.stderr, (service, 'is running, need to be killed')
        #     print >> sys.stderr, ('killing ' + service)
        #     os.kill(int(ret), SIGTERM)
        #
        #     while check_running(service):
        #         print >> sys.stderr, ('wait %s to shutdown' % service)
        #         sleep(1)
        #
        #     print >> sys.stderr, (service, 'really shutdown')

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


if __name__ == "__main__":
    main()
