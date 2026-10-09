"""Hardware preference migration and adapter replacement preservation."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from backend.infrastructure.hardware import create_track_system, hardware_profile, hardware_profiles, validate_hardware
from backend.infrastructure.interfaces import ConnectionState, ConnectionStatus, TrackSnapshot
from backend.infrastructure.settings import DEFAULT_SETTINGS, SQLiteSettingsRepository, validate_settings
from backend.runtime import ControllerRuntime
from backend.services.dispatcher import ControlMode


class HardwareSettingsTests(unittest.TestCase):
    def test_legacy_saved_endpoint_and_wlan_migrate_without_activation(self):
        repository = SQLiteSettingsRepository()
        self.addCleanup(repository.close)
        old = {key: value for key, value in DEFAULT_SETTINGS.items() if key != "hardware"}
        old.update(z21_host="10.1.2.3", z21_port=21106, z21_wlan_enabled=True)
        with repository._connection:
            repository._connection.execute("INSERT INTO app_settings VALUES(1, ?)", (json.dumps(old),))
        with patch("backend.infrastructure.hardware.create_track_system") as factory:
            loaded = repository.load()
            self.assertEqual(loaded["hardware"]["host"], "10.1.2.3")
            self.assertEqual(loaded["hardware"]["port"], 21106)
            self.assertEqual(loaded["hardware"]["transport"], "wlan")
            factory.assert_not_called()

    def test_profile_switch_resets_port_protocol_and_connection_type(self):
        initial = validate_settings({"hardware": {"system": "marklin_cs3", "decoder_protocol": "mfx", "transport": "wlan"}})
        self.assertEqual(initial["hardware"]["port"], 15731)
        serial = validate_settings({"hardware": {"system": "xpressnet", "serial_port": "COM4"}}, initial)
        self.assertEqual(serial["hardware"]["decoder_protocol"], "dcc")
        self.assertEqual(serial["hardware"]["transport"], "serial")
        z21 = validate_settings({"hardware": {"system": "z21"}}, serial)
        self.assertEqual(z21["hardware"]["port"], 21105)
        self.assertEqual(z21["hardware"]["transport"], "lan")

    def test_new_and_legacy_z21_preferences_stay_synchronized(self):
        initial = validate_settings({"z21_host": "10.1.2.3", "z21_port": 21106, "z21_wlan_enabled": True})
        self.assertEqual(initial["hardware"]["host"], "10.1.2.3")
        self.assertEqual(initial["hardware"]["transport"], "wlan")
        updated = validate_settings({"hardware": {"host": "10.2.3.4", "port": 21107, "transport": "lan"}}, initial)
        self.assertEqual(updated["z21_host"], "10.2.3.4")
        self.assertEqual(updated["z21_port"], 21107)
        self.assertFalse(updated["z21_wlan_enabled"])

    def test_other_station_does_not_overwrite_saved_z21_endpoint(self):
        value = validate_settings({"hardware": {"system": "ecos", "host": "10.3.4.5"}})
        self.assertEqual(value["hardware"]["port"], 15471)
        self.assertEqual(value["z21_host"], DEFAULT_SETTINGS["z21_host"])
        self.assertEqual(validate_settings({"theme": "dark"}, value)["hardware"], value["hardware"])

    def test_invalid_profiles_endpoints_and_transports_are_rejected(self):
        for patch_value in ({"system": "unknown"}, {"port": True}, {"host": "http://station"},
                            {"system": "xpressnet", "transport": "wlan"}, {"baudrate": 1},
                            {"decoder_protocol": "mfx"}, {"transport": "udp"}):
            with self.subTest(value=patch_value), self.assertRaises(ValueError):
                validate_hardware(patch_value)

    def test_registry_reports_implemented_capabilities_and_wire_protocols(self):
        profiles = {profile["id"]: profile for profile in hardware_profiles()}
        self.assertEqual(len(profiles), 9)
        self.assertTrue(profiles["marklin_cs3"]["supports_wlan"])
        self.assertFalse(profiles["xpressnet"]["supports_wlan"])
        self.assertEqual(profiles["xpressnet"]["default_baudrate"], 57600)
        self.assertTrue(profiles["xpressnet"]["capabilities"]["feedback"])
        self.assertFalse(profiles["marklin_cs3"]["capabilities"]["programming"])
        self.assertTrue(hardware_profile("z21").capabilities["programming"])
        self.assertEqual(profiles["ecos"]["transport"], "tcp")


class HardwareRuntimeTests(unittest.TestCase):
    def test_z21_compatible_profiles_open_same_adapter_with_selected_endpoint(self):
        with patch("backend.infrastructure.z21.Z21LanTransport") as transport_class:
            transport = transport_class.return_value
            transport.open.return_value = None
            for system in ("z21", "z21_white", "z21_start", "dr5000"):
                track = create_track_system(system, host="10.1.2.3", port=21106, transport="wlan")
                self.assertIs(track.transport, transport)
                transport_class.assert_called_with("10.1.2.3", port=21106)
            self.assertEqual(transport.open.call_count, 4)

    def test_factory_failure_closes_open_transport(self):
        with patch("backend.infrastructure.z21.Z21LanTransport") as transport_class:
            transport_class.return_value.open.side_effect = OSError("cannot bind")
            with self.assertRaises(OSError):
                create_track_system("z21")
            transport_class.return_value.close.assert_called_once()

    def test_runtime_adapter_replacement_retains_models_and_rebinds_services(self):
        runtime = ControllerRuntime.create()
        self.addCleanup(runtime.close)
        old_track = runtime.track
        objects = (runtime.layout, runtime.scheduler, runtime.dispatcher, runtime.train_database, runtime.layout_repository)
        track = MagicMock()
        track.check_connection.return_value = ConnectionStatus(ConnectionState.CONNECTED)
        track.feedback_groups.return_value = ()
        track.tick.return_value = TrackSnapshot(1, .1, False)
        track.get_snapshot.return_value = TrackSnapshot(1, .1, False)
        self.assertIs(runtime.replace_track(track, hardware_system="marklin_cs3", decoder_protocol="mfx"), old_track)
        self.assertEqual(objects, (runtime.layout, runtime.scheduler, runtime.dispatcher, runtime.train_database, runtime.layout_repository))
        self.assertIs(runtime.dispatcher.track_system, track)
        self.assertIs(runtime.calibration.track, track)
        self.assertIs(runtime.coordinate_movement._track, track)
        runtime.add_train("train", "B01", address=123)
        track.register_train.assert_called_once_with("train", 123, decoder_protocol="mfx")
        runtime.tick()
        track.check_connection.assert_called_once()

    def test_any_physical_adapter_link_loss_stops_dispatcher(self):
        runtime = ControllerRuntime.create()
        self.addCleanup(runtime.close)
        track = MagicMock()
        track.check_connection.return_value = ConnectionStatus(ConnectionState.ERROR, detail="lost")
        track.feedback_groups.return_value = ()
        track.tick.return_value = TrackSnapshot(1, .1, False)
        track.get_snapshot.return_value = TrackSnapshot(1, .1, False)
        runtime.replace_track(track, hardware_system="ecos")
        runtime.add_train("train", "B01", address=42)
        runtime.dispatcher.set_mode("train", ControlMode.MANUAL)
        runtime.tick()
        track.stop_train.assert_called_with("train")


if __name__ == "__main__":
    unittest.main()
