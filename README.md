# fluxmonitor

#### Guide: Deploy on clean raspberrypi dabian destro (2015-02-02) ####


## Check List ##
### Linux ###
#### Wifi ####
Because scanning wifi access point require root privilege. fluxmonitor
split wifi scanning function to a standalone script.

Attention:
On linux, fluxmonidord require following sudo privilege in sudoers config:
```
FLUXMONITORD_CMD = /sbin/ifconfig, /sbin/wpa_supplicant, /sbin/dhclient, /usr/sbin/hostapd

{USER} ALL=(ALL) NOPASSWD: FLUXMONITORD_CMD
```
Please ensure user has such privilege to execute command in sudoer
list and remember allow execute these command with out `PASSWORD`
