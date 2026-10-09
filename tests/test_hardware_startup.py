"""Startup selection checks do not open station connections."""
from __future__ import annotations

from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.api.server import startup_hardware, startup_z21_endpoint, startup_z21_transport
from backend.infrastructure.hardware import hardware_profiles
from backend.infrastructure.settings import SQLiteSettingsRepository, validate_settings
from backend.infrastructure.wlan import IF_TYPE_IEEE80211, WlanAdapter
from desktop_app import DesktopController


class Route:
    def __init__(self):
        self.hosts = []

    def best_interface(self, host):
        self.hosts.append(host)
        return 7

    def interface(self, index):
        return WlanAdapter(index, IF_TYPE_IEEE80211, 5, "Station Wi-Fi")


class HardwareStartupTests(unittest.TestCase):
    def saved(self, system, **settings):
        return validate_settings({"hardware": {"system": system, "serial_port": "COM8", **settings}})

    def test_every_saved_profile_defaults_to_simulation_without_activation(self):
        with patch.object(socket, "socket", side_effect=AssertionError("startup resolver opened a socket")):
            for profile in hardware_profiles():
                with self.subTest(profile=profile["id"]):
                    config, transport, status = startup_hardware(self.saved(profile["id"]), {})
                    self.assertEqual(config["system"], "simulation")
                    self.assertEqual(transport, "simulation")
                    self.assertEqual(status["state"], "inactive")

    def test_saved_and_explicit_selection_preserve_correct_ports_for_every_profile(self):
        for profile in hardware_profiles():
            with self.subTest(profile=profile["id"]):
                saved = self.saved(profile["id"])
                for selector in ("hardware", profile["id"]):
                    config, transport, status = startup_hardware(saved, {"H0_TRACK_SYSTEM": selector})
                    self.assertEqual(config["system"], profile["id"])
                    self.assertEqual(config["port"], profile["default_port"])
                    self.assertTrue(status["ready"])
                    self.assertEqual(transport, profile["transport"] if profile["transport"] in ("serial", "simulation") else "lan")

    def test_environment_overrides_network_and_serial_connections(self):
        config, _, _ = startup_hardware(self.saved("z21"), {
            "H0_TRACK_SYSTEM": "ecos", "H0_HARDWARE_HOST": "10.2.3.4",
            "H0_HARDWARE_PORT": "15472", "H0_HARDWARE_DECODER_PROTOCOL": "mfx",
            "H0_Z21_HOST": "10.2.3.5", "H0_Z21_PORT": "21106",
        })
        self.assertEqual((config["system"], config["host"], config["port"], config["decoder_protocol"]), ("ecos", "10.2.3.4", 15472, "mfx"))
        config, transport, _ = startup_hardware(self.saved("z21"), {
            "H0_HARDWARE_SYSTEM": "xpressnet", "H0_HARDWARE_SERIAL_PORT": "/dev/ttyUSB0",
            "H0_HARDWARE_BAUDRATE": "19200",
        })
        self.assertEqual((config["system"], transport, config["serial_port"], config["baudrate"]), ("xpressnet", "serial", "/dev/ttyUSB0", 19200))

    def test_explicit_simulation_ignores_station_activation_environment(self):
        config, transport, _ = startup_hardware(self.saved("marklin_cs3"), {"H0_TRACK_SYSTEM": "simulation", "H0_Z21_HOST": "10.2.3.4", "H0_HARDWARE_SYSTEM": "ecos"})
        self.assertEqual((config["system"], transport), ("simulation", "simulation"))

    def test_invalid_selection_endpoint_or_serial_port_fails_before_creation(self):
        cases = ({"H0_TRACK_SYSTEM": "typo"}, {"H0_TRACK_SYSTEM": "ecos", "H0_HARDWARE_PORT": "wrong"},
                 {"H0_TRACK_SYSTEM": "ecos", "H0_HARDWARE_HOST": "invalid"}, {"H0_TRACK_SYSTEM": "xpressnet"})
        for environment in cases:
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                startup_hardware(validate_settings({}), environment)

    def test_wlan_checks_effective_windows_route_for_all_network_profiles(self):
        for profile in hardware_profiles():
            if not profile["supports_wlan"]:
                continue
            with self.subTest(profile=profile["id"]):
                route = Route()
                config, transport, status = startup_hardware(self.saved(profile["id"], transport="wlan"),
                    {"H0_TRACK_SYSTEM": "hardware", "H0_HARDWARE_HOST": "10.2.3.4"}, wlan_route_api=route, platform_name="win32")
                self.assertEqual(route.hosts, ["10.2.3.4"])
                self.assertEqual((transport, status["state"]), ("wlan", "ready"))
                self.assertIn(profile["label"], status["detail"])

    def test_non_windows_wlan_uses_station_protocol_without_windows_inspection(self):
        route = Route()
        config, transport, status = startup_hardware(self.saved("ecos", transport="wlan"),
            {"H0_TRACK_SYSTEM": "hardware"}, wlan_route_api=route, platform_name="linux")
        self.assertEqual(route.hosts, [])
        self.assertEqual(transport, "wlan")
        self.assertIn("does not perform Windows", status["detail"])

    def test_legacy_z21_helpers_and_implicit_environment_activation_remain(self):
        saved = validate_settings({"z21_host": "10.0.0.111", "z21_port": 21106})
        self.assertEqual(startup_z21_endpoint(saved, {}), (None, 21106))
        self.assertEqual(startup_z21_endpoint(saved, {"H0_TRACK_SYSTEM": "z21"}), ("10.0.0.111", 21106))
        self.assertEqual(startup_z21_transport(saved, {"H0_TRACK_SYSTEM": "z21"})[:3], ("10.0.0.111", 21106, "lan"))
        config, _, _ = startup_hardware(saved, {"H0_Z21_HOST": "10.0.0.112", "H0_Z21_PORT": "21107"})
        self.assertEqual((config["system"], config["host"], config["port"]), ("z21", "10.0.0.112", 21107))

    def test_desktop_physical_start_uses_saved_non_z21_station(self):
        class Server:
            server_port = 54321

            def serve_forever(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            repository = SQLiteSettingsRepository(path / "controller.sqlite3")
            repository.save(self.saved("ecos", host="10.2.3.4", port=15472))
            repository.close()
            with patch("desktop_app.ControllerApplication.sample", return_value=Mock()) as create, patch("desktop_app.make_server", return_value=Server()):
                controller = DesktopController(path, physical=True, port=0)
                controller.thread.join(timeout=1)
                controller.instance_lock.close()
            self.assertEqual(create.call_args.kwargs["hardware_system"], "ecos")
            self.assertEqual(create.call_args.kwargs["hardware_connection"]["host"], "10.2.3.4")
            self.assertIsNone(create.call_args.kwargs["z21_host"])


if __name__ == "__main__":
    unittest.main()
