
import argparse
import sys

from fluxmonitor.misc.flux_argparse import add_config_arguments, \
    apply_config_arguments


def main():
    parser = argparse.ArgumentParser(description='flux info')
    add_config_arguments(parser)

    options = parser.parse_args()
    apply_config_arguments(options)

    from fluxmonitor import halprofile
    from fluxmonitor import security

    # TODO: Add more information here
    print("""Flux info:
  Module: %(module)s
  Serial: %(serial)s""" % {
        "module": halprofile.get_model_id(),
        "serial": security.get_serial()
    })


if __name__ == "__main__":
    sys.exit(main())
