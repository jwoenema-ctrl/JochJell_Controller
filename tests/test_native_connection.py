import unittest
from unittest.mock import Mock
from native_connection import NativeConnectionAPI


class NativeConnectionTests(unittest.TestCase):
    def setUp(self):
        self.window = Mock()
        self.window.get_current_url.return_value = "http://127.0.0.1:8765/#settings"
        self.controller = Mock(url="http://127.0.0.1:8765")
        self.switch = Mock()
        self.api = NativeConnectionAPI(lambda: self.window, lambda: self.controller, self.switch)

    def test_confirmed_switch(self):
        self.window.create_confirmation_dialog.return_value = True
        self.assertTrue(self.api.switch_mode("z21")["accepted"])
        self.switch.assert_called_once_with(True)

    def test_cancel_does_not_connect(self):
        self.window.create_confirmation_dialog.return_value = False
        self.assertTrue(self.api.switch_mode("z21")["cancelled"])
        self.switch.assert_not_called()

    def test_external_pages_and_invalid_modes_rejected(self):
        for url in ("https://example.com/", "http://127.0.0.1:87650/", "http://127.0.0.1:8765/scans/files/remote.html"):
            self.window.get_current_url.return_value = url
            self.assertFalse(self.api.switch_mode("z21")["accepted"])
        self.assertFalse(self.api.switch_mode("unexpected")["accepted"])
        self.switch.assert_not_called()
