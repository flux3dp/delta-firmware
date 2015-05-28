
import argparse
import sys

from fluxmonitor.misc.flux_argparse import add_config_arguments, \
    apply_config_arguments
from fluxmonitor.misc.control_mutex import ControlLock
from fluxmonitor.launcher import create_logger


def main():
    parser = argparse.ArgumentParser(description='flux scanner')
    add_config_arguments(parser)

    options = parser.parse_args()

    with ControlLock("scanner"):
        apply_config_arguments(options)
        create_logger(options)

        from fluxmonitor.controller.scanner import Scanner

        robot = Scanner(options)
        try:
            robot.run()
        finally:
            robot.close()

        return 0


if __name__ == "__main__":
    sys.exit(main())