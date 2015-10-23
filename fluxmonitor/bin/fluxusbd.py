
import argparse
import psutil
import sys

from fluxmonitor.misc.flux_argparse import add_daemon_arguments, \
    apply_daemon_arguments
from fluxmonitor.launcher import deamon_entry


def main():
    parser = argparse.ArgumentParser(description='flux usb deamon')
    add_daemon_arguments("fluxusbd", parser)

    if any('start_service' in p for p in sys.argv):
        options = parser.parse_args(['--pid', '/var/run/fluxusbd.pid', '--log', '/var/log/fluxusbd.log', '—daemon'])
    else:
        options = parser.parse_args()

    apply_daemon_arguments(options)

    if options.stop_daemon:
        try:
            pid_handler = open(options.pidfile, 'r', 0)
            pid = int(pid_handler.read(), 10)

            proc = psutil.Process(pid)
            proc.terminate()

            proc.wait(5.)
            sys.exit(0)
        except psutil.TimeoutExpired as e:
            print("Error: Timeout while stopping daemon")
        except Exception as e:
            print("Error: %s" % e)
            sys.exit(1)
    else:
        return_code = deamon_entry(
            options,
            service="fluxmonitor.services.usb.UsbService")
        sys.exit(return_code)


if __name__ == "__main__":
    main()
