#!/usr/bin/env python

"""
flux_network_config is a simple tool shows how to organize and send network
configuration to fluxmonitord daemon.

Note: You have to ensure you have a fluxmonitord is running and listen to
proper unixsocket
"""

from pprint import pprint
import argparse
import socket
import json

from fluxmonitor.misc import network_config_encoder as NCE
from fluxmonitor.misc.flux_argparse import add_config_arguments, \
    apply_config_arguments


parser = argparse.ArgumentParser(description='network config')
add_config_arguments(parser)
parser.add_argument('--if', dest='ifname', type=str, required=True,
                    help='Interface, example: wlan0')

parser.add_argument('--unset', dest='unset', action='store_const', const=True,
                    default=False, help='Unset')

parser.add_argument('--ip', dest='ipaddr', type=str, default=None,
                    help='IP Address, example: 192.168.1.2. '
                         'If no ip given, use dhcp')
parser.add_argument('--mask', dest='mask', type=int, default=24,
                    help='Mask, example: 24')
parser.add_argument('--route', dest='route', type=str, default=None,
                    help='Route, example: 192.168.1.1')
parser.add_argument('--dns', dest='ns', type=str, default=None, nargs=1,
                    help='Route, example: 192.168.1.1')
parser.add_argument('--ssid', dest='ssid', type=str, default=None,
                    help='SSID, example:: FLUX')
parser.add_argument('--security', dest='security', type=str, default=None,
                    choices=['', 'WEP', 'WPA-PSK', 'WPA2-PSK'],
                    help='wifi security')
parser.add_argument('--psk', dest='psk', type=str, default=None,
                    help='WPA-PSK')
parser.add_argument('--wepkey', dest='wepkey', type=str, default=None,
                    help='wepkey')

options = parser.parse_args()
apply_config_arguments(options)

from fluxmonitor.config import NETWORK_MANAGE_ENDPOINT

# ======== Build config message here ========
payload = {"ifname": options.ifname}

# Ipv4 Config
if options.ipaddr:
    # Check ip configs
    if not options.route:
        raise RuntimeError("--netmask is required")
    if not options.ns:
        raise RuntimeError("--dns is required")

    payload.update({
        "method": "static",
        "mask": options.mask,
        "ipaddr": options.ipaddr,
        "route": options.route,
        "ns": options.ns,
    })

elif not options.unset:
    # Using dhcp
    payload.update({"method": "dhcp"})

# Wireless Config
if options.ssid:
    # Check wifi setting
    if options.security == "":
        # No security
        payload.update({
            "ssid": options.ssid
        })
    elif options.security == "WEP":
        if not options.wepkey:
            raise RuntimeError("--wepkey is required")
        payload.update({
            "ssid": options.ssid,
            "security": "WEP",
            "wepkey": options.wepkey
        })
    elif options.security in ['WPA-PSK', 'WPA2-PSK']:
        payload.update({
            "ssid": options.ssid,
            "security": options.security,
            "psk": options.psk
        })
    else:
        raise RuntimeError("Unknow security option: %s" % options.security)

print("Payload:")
pprint(payload)

# ======== Send message to remote ========
print("\nOpen communicate socket at: %s" % NETWORK_MANAGE_ENDPOINT)
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.connect(NETWORK_MANAGE_ENDPOINT)

s.send(b"%s\x00%s" % (b"config_network", NCE.to_bytes(payload)))
print("Message sent.")
