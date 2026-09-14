"""Offline tests for the Roco 10814 WLAN transport profile."""

from __future__ import annotations

from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.api.server import ControllerApplication, startup_z21_transport
from backend.infrastructure.settings import DEFAULT_SETTINGS, SQLiteSettingsRepository, validate_settings
from backend.infrastructure.wlan import (
    IF_TYPE_IEEE80211,
    WlanAdapter,
    WlanPreflightError,
    preflight_z21_wlan,
)
from desktop_app import DesktopController
from native_connection import NativeConnectionAPI


class FakeRouteAPI:
    def __init__(self, adapter: WlanAdapter | None = None, *, error: Exception | None = None):
        self.adapter_value = adapter or WlanAdapter(7, IF_TYPE_IEEE80211, 5, "Test Wi-Fi")
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def best_interface(self, host: str) -> int:
        self.calls.append(("best_interface", host))
        if self.error is not None:
            raise self.error
        return self.adapter_value.interface_index

    def interface(self, interface_index: int) -> WlanAdapter:
        self.calls.append(("interface", interface_index))
        return self.adapter_value


class WlanPreflightTests(unittest.TestCase):
    def test_active_wifi_route_is_accepted_without_opening_a_socket(self) -> None:
        route = FakeRouteAPI()
        with patch.object(socket, "socket", side_effect=AssertionError("preflight opened a socket")):
            status = preflight_z21_wlan("192.168.0.111", route_api=route, platform_name="win32")
        self.assertEqual(status["profile"], "wlan")
        self.assertEqual(status["state"], "ready")
        self.assertTrue(status["ready"])
        self.assertEqual(status["interface_index"], 7)
        self.assertEqual(route.calls, [("best_interface", "192.168.0.111"), ("interface", 7)])

    def test_non_wifi_and_inactive_routes_are_rejected_actionably(self) -> None:
        cases = (
            (WlanAdapter(4, 6, 5, "Ethernet"), "non-WLAN"),
            (WlanAdapter(7, IF_TYPE_IEEE80211, 2, "Wi-Fi"), "not connected"),
        )
        for adapter, expected in cases:
            with self.subTest(adapter=adapter), self.assertRaisesRegex(WlanPreflightError, expected):
                preflight_z21_wlan(
                    "192.168.0.111",
                    route_api=FakeRouteAPI(adapter),
                    platform_name="win32",
                )

    def test_non_windows_failure_explains_safe_alternatives_without_probing(self) -> None:
        route = FakeRouteAPI()
        with self.assertRaisesRegex(WlanPreflightError, "supported only on Windows") as raised:
            preflight_z21_wlan("192.168.0.111", route_api=route, platform_name="linux")
        self.assertIn("simulation", str(raised.exception))
        self.assertEqual(route.calls, [])

    def test_windows_api_errors_are_wrapped_with_connection_guidance(self) -> None:
        with self.assertRaisesRegex(WlanPreflightError, "Join the Roco/Z21 Wi-Fi network"):
            preflight_z21_wlan(
                "192.168.0.111",
                route_api=FakeRouteAPI(error=OSError("route table unavailable")),
                platform_name="win32",
            )


class WlanSettingsAndStartupTests(unittest.TestCase):
    def test_boolean_defaults_false_validates_and_persists(self) -> None:
        self.assertIs(DEFAULT_SETTINGS["z21_wlan_enabled"], False)
        for invalid in (0, 1, "true", None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "must be a boolean"):
                validate_settings({"z21_wlan_enabled": invalid})
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteSettingsRepository(Path(directory) / "controller.sqlite3")
            try:
                saved = repository.save({**DEFAULT_SETTINGS, "z21_wlan_enabled": True})
                self.assertTrue(saved["z21_wlan_enabled"])
                self.assertTrue(repository.load()["z21_wlan_enabled"])
            finally:
                repository.close()

    def test_simulation_and_lan_profiles_never_run_wlan_preflight(self) -> None:
        never = FakeRouteAPI(error=AssertionError("unexpected WLAN preflight"))
        saved = {**DEFAULT_SETTINGS, "z21_wlan_enabled": True}
        host, port, profile, status = startup_z21_transport(
            saved,
            {"H0_TRACK_SYSTEM": "simulation"},
            wlan_route_api=never,
            platform_name="win32",
        )
        self.assertEqual((host, port, profile), (None, 21105, "simulation"))
        self.assertEqual(status["state"], "inactive")
        self.assertEqual(never.calls, [])

        saved["z21_wlan_enabled"] = False
        host, port, profile, status = startup_z21_transport(
            saved,
            {"H0_TRACK_SYSTEM": "z21"},
            wlan_route_api=never,
            platform_name="win32",
        )
        self.assertEqual((host, port, profile), ("192.168.0.111", 21105, "lan"))
        self.assertEqual(status["state"], "not_required")
        self.assertEqual(never.calls, [])

    def test_physical_wlan_startup_checks_the_effective_host(self) -> None:
        route = FakeRouteAPI()
        saved = {**DEFAULT_SETTINGS, "z21_wlan_enabled": True}
        host, port, profile, status = startup_z21_transport(
            saved,
            {
                "H0_TRACK_SYSTEM": "z21",
                "H0_Z21_HOST": "192.168.0.112",
                "H0_Z21_PORT": "21106",
            },
            wlan_route_api=route,
            platform_name="win32",
        )
        self.assertEqual((host, port, profile), ("192.168.0.112", 21106, "wlan"))
        self.assertEqual(status["host"], "192.168.0.112")
        self.assertEqual(route.calls[0], ("best_interface", "192.168.0.112"))

    def test_runtime_exposes_active_and_next_transport_profiles(self) -> None:
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        payload = app.update_settings({"z21_wlan_enabled": True})
        self.assertEqual(payload["runtime"]["transport_profile"], "simulation")
        self.assertEqual(payload["runtime"]["next_transport_profile"], "wlan")
        self.assertEqual(payload["runtime"]["transport_status"]["state"], "inactive")
        self.assertFalse(payload["runtime"]["restart_required"])

    def test_active_wlan_status_and_profile_changes_are_reported(self) -> None:
        status = {
            "profile": "wlan",
            "state": "ready",
            "ready": True,
            "host": "192.168.0.111",
            "interface_index": 7,
            "interface_name": "Test Wi-Fi",
            "detail": "ready",
        }
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        app.z21_host = "192.168.0.111"
        app.z21_transport_profile = "wlan"
        app.z21_transport_status = status
        app.update_settings({"z21_wlan_enabled": True})
        payload = app.settings_payload()
        self.assertEqual(payload["runtime"]["transport_profile"], "wlan")
        self.assertEqual(payload["runtime"]["transport_status"], status)
        self.assertFalse(payload["runtime"]["restart_required"])
        self.assertTrue(app.update_settings({"z21_wlan_enabled": False})["runtime"]["restart_required"])

    def test_desktop_physical_start_reads_saved_wlan_before_controller_creation(self) -> None:
        class DummyServer:
            server_port = 54321

            def serve_forever(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            repository = SQLiteSettingsRepository(path / "controller.sqlite3")
            repository.save({**DEFAULT_SETTINGS, "z21_wlan_enabled": True})
            repository.close()
            route = FakeRouteAPI()
            fake_app = Mock()
            created_after_preflight = False

            def create_application(**kwargs):
                nonlocal created_after_preflight
                created_after_preflight = bool(route.calls)
                return fake_app

            with patch("desktop_app.ControllerApplication.sample", side_effect=create_application) as create, \
                    patch("desktop_app.make_server", return_value=DummyServer()):
                controller = DesktopController(
                    path,
                    physical=True,
                    port=0,
                    wlan_route_api=route,
                    platform_name="win32",
                )
                controller.thread.join(timeout=1)
                controller.instance_lock.close()
            self.assertTrue(created_after_preflight)
            kwargs = create.call_args.kwargs
            self.assertEqual(kwargs["z21_transport_profile"], "wlan")
            self.assertEqual(kwargs["z21_transport_status"]["state"], "ready")


class WlanNativeResponseTests(unittest.TestCase):
    def test_confirmed_native_switch_returns_transport_profile_and_status(self) -> None:
        window = Mock()
        window.get_current_url.return_value = "http://127.0.0.1:8765/#settings"
        window.create_confirmation_dialog.return_value = True
        app = Mock()
        app.settings_payload.return_value = {
            "runtime": {
                "connection_mode": "z21",
                "transport_profile": "wlan",
                "transport_status": {"profile": "wlan", "state": "ready", "ready": True},
            }
        }
        controller = Mock(url="http://127.0.0.1:8765", app=app)
        api = NativeConnectionAPI(lambda: window, lambda: controller, Mock())
        response = api.switch_mode("z21")
        self.assertEqual(
            response,
            {
                "accepted": True,
                "mode": "z21",
                "transport_profile": "wlan",
                "transport_status": {"profile": "wlan", "state": "ready", "ready": True},
            },
        )


if __name__ == "__main__":
    unittest.main()
