#!/usr/bin/env python

import argparse
import getpass

from fluxmonitor.misc.flux_argparse import add_config_arguments, \
    apply_config_arguments

parser = argparse.ArgumentParser(description='set password')
add_config_arguments(parser)

options = parser.parse_args()
apply_config_arguments(options)


pw1 = getpass.getpass("Password: ")
pw2 = getpass.getpass("Confirm Password: ")

if pw1 != pw2:
    raise RuntimeError("Password dnot match")


from fluxmonitor.security.passwd import set_password
set_password(pw1)
