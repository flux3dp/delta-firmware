
import unittest

from fluxmonitor.misc import network_config_encoder as NCE


class NWConfigEncoderTest(unittest.TestCase):
    def test_dhcp_plaint_wifi(self):
        buf = b"method=dhcp\x00ssid=UNITTEST\x00TRASH=TRASH"
        real_options = {"method": "dhcp", "ssid": "UNITTEST",
                        "wifi_mode": "client", "security": None}
        options = NCE.parse_bytes(buf)
        self.assertEqual(options, real_options)

        buf2 = NCE.to_bytes(options)
        self.assertEqual(NCE.parse_bytes(buf2), real_options)

    def test_static_ip_no_wifi(self):
        buf = b"method=static\x00ipaddr=192.168.100.200\x00mask=24\x00" \
              b"ns=8.8.8.8,8.8.4.4"
        real_options = {"method": "static", "mask": 24,
                        "ipaddr": "192.168.100.200",
                        "ns": ["8.8.8.8", "8.8.4.4"], "route": None}
        options = NCE.parse_bytes(buf)
        self.assertEqual(options, real_options)

        buf2 = NCE.to_bytes(options)
        self.assertEqual(NCE.parse_bytes(buf2), real_options)

    def test_dhcp_psk_wifi(self):
        buf = b"method=dhcp\x00ssid=UNITTEST\x00security=WPA2-PSK\x00" \
              b"psk=wifipasswd12345678"
        real_options = {"method": "dhcp", "ssid": "UNITTEST",
                        "wifi_mode": "client", "security": "WPA2-PSK",
                        "psk": "wifipasswd12345678"}
        options = NCE.parse_bytes(buf)
        self.assertEqual(options, real_options)

        buf2 = NCE.to_bytes(options)
        self.assertEqual(NCE.parse_bytes(buf2), real_options)

    def test_bad_options(self):
        buf = b"method=static\x00ssid=UNITTEST\x00TRASH=TRASH"
        self.assertRaises(KeyError, NCE.parse_bytes, buf)

        buf = b"method=dhcp\x00ssid=UNITTEST\x00security=WPA2-PSK"
        self.assertRaises(KeyError, NCE.parse_bytes, buf)
