
import argparse
import psutil
import sys

from fluxmonitor.misc.flux_argparse import add_daemon_arguments, \
    apply_daemon_arguments
from fluxmonitor.watcher.network import NetworkWatcher
from fluxmonitor.launcher import deamon_entry


def main():
    parser = argparse.ArgumentParser(description='flux network deamon')
    add_daemon_arguments("fluxnetworkd", parser)
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
        return_code = main(options, module=NetworkWatcher)
        sys.exit(return_code)


if __name__ == "__main__":
    main()