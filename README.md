# delta-firmware

FLUX Delta Series Firmware based on Linux System / Python

The package was former named "fluxmonitor, and it reference itself as "fluxmonitor" in the code.

There are two setup scripts here:
* devsetup.py
* setup.py

Some source codes are writen in cython style (\*.pyx in src/). 
It require Cython to generate C codes from *.pyx.

`devsetup.py` will invoke Cython to generate C codes from *.pyx and compile it.

`setup.py` will compile C codes directly. (You don't need to install Cython)
NOTE: Usually, everythime cython sources has been modified. C codes generate from Cython should be commit together.


#### Raspberrypi Checklist ####

The following packages should already installed in default environment:
* wpa_supplicant - A program can manage associate with AP
* dhclient - DHCP Client


The following packages may need install manually:
* isc-dhcp-server - DHCP Server running for AP mode
* hostapd - A program can simulate wireless device as an AP

Configuration:
Ensure all network settings are empty. No dhcp server/client and wpa_supplicant
start automatically.

