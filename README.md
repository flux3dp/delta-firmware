# fluxmonitor

#### Guide: Deploy on clean raspberrypi dabian destro (2015-02-02) ####


## Check List ##
### Linux ###
#### Wifi ####
Because scanning wifi access point require root privilege. fluxmonitor
split wifi scanning function to a standalone script.

Attention:
On linux, flux_wlan_scan will use wpa_cli and sudo commands below:
```
# sudo -n wpa_cli scan
# sudo -n wpa_cli scan_result
```
Please ensure user has such privilege to execute command in sudoer
list and remember allow execute these command with out `PASSWORD`
