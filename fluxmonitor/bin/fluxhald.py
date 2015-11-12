
import argparse
import psutil
import sys

from fluxmonitor.misc.flux_argparse import add_daemon_arguments, \
    apply_daemon_arguments
from fluxmonitor.launcher import deamon_entry


def main(params=None):
    parser = argparse.ArgumentParser(description='flux hal deamon')
    add_daemon_arguments("fluxhald", parser)
    parser.add_argument('--manually', dest='manually', action='store_const',
                        const=True, default=False, help='Connect to smoothie')
    parser.add_argument("--mb", dest='mb', type=str, default=None,
                        help='Mainboard Serial Port')
    parser.add_argument("--hb", dest='hb', type=str, default=None,
                        help='Headboard Serial Port')

    options = parser.parse_args(params)
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
            service="fluxmonitor.services.hal.HalService")
        sys.exit(return_code)


if __name__ == "__main__":
    main()
