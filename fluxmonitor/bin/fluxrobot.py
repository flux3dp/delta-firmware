
import argparse
import sys

from fluxmonitor.misc.flux_argparse import add_daemon_arguments, \
    apply_daemon_arguments
from fluxmonitor.misc.control_mutex import ControlLock
from fluxmonitor.launcher import create_logger


def main():
    parser = argparse.ArgumentParser(description='flux robot')
    add_daemon_arguments("fluxrobot", parser)
    parser.add_argument('--task', dest='taskfile', type=str, default=None,
                        help='A g-code file, if this arg given, robot will'
                             ' enter PlayTask and run g-code automatically')

    options = parser.parse_args()

    with ControlLock("robot"):
        apply_daemon_arguments(options)
        create_logger(options)

        from fluxmonitor.controller.robot import Robot

        robot = Robot(options)
        try:
            robot.run()
        except (KeyboardInterrupt, ):
            pass
        finally:
            robot.close()

        return 0


if __name__ == "__main__":
    sys.exit(main())
