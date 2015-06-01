
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
    from fluxmonitor import config

    # TODO: Add more information here
    print("""Flux info:
  Module: %(module)s
  Serial: %(serial)s

  HAL:
    Mainboard Serial: %(mainboard_serial)s
    Headboard Serial: %(headboard_serial)s
    PC Serial: %(pc_serial)s""" % {
        "module": halprofile.get_model_id(),
        "serial": security.get_serial(),

        "mainboard_serial": config.hal_config["mainboard_uart"],
        "headboard_serial": config.hal_config["headboard_uart"],
        "pc_serial": config.hal_config["pc_uart"],
    })


if __name__ == "__main__":
    sys.exit(main())
