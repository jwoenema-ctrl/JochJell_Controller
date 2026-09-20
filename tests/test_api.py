"""Smoke tests for the dependency-free HTTP application boundary."""

from __future__ import annotations

import json
import threading
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

from backend.api.server import ControllerApplication, make_server
from backend.infrastructure.interfaces import CommandResult


class ApiTests(unittest.TestCase):
    def test_sample_tick_moves_automatic_train_progress(self) -> None:
        app = ControllerApplication.sample()
        try:
            initial_train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(initial_train["route"], ["B01", "B02", "B03", "B04"])
            self.assertEqual(initial_train["destination_block_id"], "B04")
            before = app.state()["tick"]
            app.tick(2)
            after = app.state()
            self.assertEqual(after["tick"], before + 2)
            self.assertTrue(any(event["type"] == "simulation_tick" for event in after["events"]))
            self.assertEqual(next(item for item in after["layout"]["blocks"] if item["id"] == "b02")["status"], "route")
            app.tick(50)
            self.assertEqual(next(item for item in app.state()["trains"] if item["id"] == "t1")["position"], "B02")
        finally:
            app.close()

    def test_calibrated_pinboard_target_is_validated_and_persisted(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "stop_train", "train_id": "train-3"})
            app.command({"type": "start_calibration", "train_id": "train-3", "speed_kmh": 10, "duration_ms": 100})
            deadline = time.monotonic() + 2
            while app.state()["calibration"]["active"]["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(app.state()["calibration"]["active"]["status"], "completed")
            app.command({"type": "record_calibration", "distance_mm": 50})
            app.command({"type": "set_direction", "train_id": "train-3", "direction": "reverse"})
            state = app.command({"type": "move_train_to_coordinate", "train_id": "train-3", "x": 515, "y": 150})
            target = next(item for item in state["trains"] if item["id"] == "t2")["target_coordinate"]
            self.assertEqual((target["from_node"], target["to_node"]), ("b03", "b02"))
            self.assertGreater(target["estimated_duration_ms"], 0)
        finally:
            app.close()

    def test_train_actions_can_be_recorded_and_replayed(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            started = app.command({"type": "start_recording", "train_id": "train-3", "timestamp": time.time() - 1})
            self.assertTrue(started["recording"]["active"])
            app.command({"type": "speed", "train_id": "train-3", "speed": 20})
            stopped = app.command({"type": "stop_recording", "timestamp": time.time()})
            self.assertEqual(len(stopped["recording"]["history"]), 1)
            self.assertEqual(stopped["recording"]["history"][0]["action_count"], 1)
            replayed = app.command({"type": "play_recording", "index": 0, "confirm": True})
            self.assertFalse(replayed["recording"]["active"])
            self.assertEqual(next(item for item in replayed["trains"] if item["id"] == "t2")["speed"], 0)
            control = app.runtime.dispatcher.trains["train-3"]
            self.assertEqual((control.manual_speed, control.automatic_speed), (0.0, 0.0))
        finally:
            app.close()

    def test_replayed_direction_updates_train_state(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "stop_train", "train_id": "train-3"})
            app.command({"type": "start_recording", "train_id": "train-3"})
            app.command({"type": "set_direction", "train_id": "train-3", "direction": "reverse"})
            app.command({"type": "stop_recording"})
            app.command({"type": "set_direction", "train_id": "train-3", "direction": "forward"})
            replayed = app.command({"type": "play_recording", "index": 0, "confirm": True})
            self.assertEqual(next(item for item in replayed["trains"] if item["id"] == "t2")["direction"], "Reverse")
        finally:
            app.close()

    def test_playback_rejects_power_off_and_automatic_mode_without_opt_in(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "start_recording", "train_id": "train-3"})
            app.command({"type": "speed", "train_id": "train-3", "speed": 20})
            app.command({"type": "stop_recording"})
            app.command({"type": "stop_train", "train_id": "train-3"})
            app.command({"type": "track_power", "enabled": False})
            with self.assertRaisesRegex(ValueError, "track power"):
                app.command({"type": "play_recording", "index": 0, "confirm": True})

            app.command({"type": "track_power", "enabled": True})
            app.command({"type": "set_train_mode", "train_id": "train-101", "mode": "automatic"})
            app.command({"type": "stop_train", "train_id": "train-101"})
            app.command({"type": "start_recording", "train_id": "train-101"})
            app.command({"type": "speed", "train_id": "train-101", "speed": 20})
            app.command({"type": "stop_recording"})
            app.command({"type": "stop_train", "train_id": "train-101"})
            with self.assertRaisesRegex(ValueError, "automatic=true"):
                app.command({"type": "play_recording", "index": 1, "confirm": True})
            replayed = app.command({"type": "play_recording", "index": 1, "confirm": True, "automatic": True})
            self.assertEqual(next(item for item in replayed["trains"] if item["id"] == "t1")["speed"], 0)
        finally:
            app.close()

    def test_playback_failure_after_motion_stops_and_resets_targets(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "start_recording", "train_id": "train-3"})
            app.command({"type": "speed", "train_id": "train-3", "speed": 20})
            app.command({"type": "set_train_function", "train_id": "train-3", "function_number": 2, "enabled": True})
            app.command({"type": "stop_recording"})
            app.command({"type": "stop_train", "train_id": "train-3"})
            track = app.runtime.track
            with patch.object(track, "stop_train", wraps=track.stop_train) as stop_train,                  patch.object(track, "set_train_function", return_value=CommandResult(False, "set_train_function", "rejected")):
                with self.assertRaisesRegex(ValueError, "rejected"):
                    app.command({"type": "play_recording", "index": 0, "confirm": True})
            self.assertTrue(stop_train.called)
            control = app.runtime.dispatcher.trains["train-3"]
            self.assertEqual((control.manual_speed, control.automatic_speed), (0.0, 0.0))
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-3")["speed"], 0)
        finally:
            app.close()

    def test_recorded_decoder_function_replays_in_simulation(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "start_recording", "train_id": "train-3"})
            app.command({"type": "set_train_function", "train_id": "train-3", "function_number": 2, "enabled": True})
            app.command({"type": "stop_recording"})
            replayed = app.command({"type": "play_recording", "index": 0, "confirm": True})
            train = next(item for item in replayed["trains"] if item["id"] == "t2")
            self.assertTrue(train["decoder_function_states"]["2"])
        finally:
            app.close()

    def test_calibrated_coordinate_execution_stops_after_bounded_timer(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "stop_train", "train_id": "train-3"})
            app.runtime.train_database.add_calibration(
                "train-3", speed_kmh=10, duration_ms=100, measured_distance_mm=50,
                created_at="2026-01-01T00:00:00Z",
            )
            app.command({"type": "set_direction", "train_id": "train-3", "direction": "reverse"})
            app.command({"type": "move_train_to_coordinate", "train_id": "train-3", "x": 515, "y": 150})
            running = app.command({"type": "execute_coordinate_move", "train_id": "train-3", "confirm": True})
            self.assertEqual(running["coordinate_execution"]["state"], "running")
            time.sleep(0.35)
            self.assertIn(app.state()["coordinate_execution"]["state"], {"completed", "stopped"})
        finally:
            app.close()

    def test_schedule_rejects_off_track_coordinate_and_canonicalizes_valid_one(self) -> None:
        app = ControllerApplication.sample()
        try:
            with self.assertRaisesRegex(ValueError, "not on the configured track"):
                app.command({
                    "type": "add_schedule",
                    "schedule": {"id": "off-track", "train_id": "train-3", "station_id": "ST01", "platform": "P01", "destination_coordinate": {"x": 10, "y": 10}},
                })
            result = app.command({
                "type": "add_schedule",
                "schedule": {"id": "on-track", "train_id": "train-3", "station_id": "ST01", "platform": "P01", "destination_coordinate": {"x": 328, "y": 150}},
            })
            schedule = next(item for item in result["schedules"] if item["id"] == "on-track")
            self.assertEqual((schedule["destination_coordinate"]["from_node"], schedule["destination_coordinate"]["to_node"]), ("b01", "b02"))
        finally:
            app.close()

    def test_schedule_departure_targets_calibrated_coordinate_for_automatic_train(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.runtime.train_database.add_calibration(
                "train-101", speed_kmh=10, duration_ms=100, measured_distance_mm=50,
                created_at="2026-01-01T00:00:00Z",
            )
            app.command({
                "type": "add_schedule",
                "schedule": {
                    "id": "coordinate-departure", "time": "00:01", "service": "Calibrated run",
                    "number": "101", "train_id": "train-101", "station_id": "ST01", "platform": "P01",
                    "destination_coordinate": {"x": 300, "y": 150},
                },
            })
            app.runtime.scheduler.reset(tick=0)
            app.runtime.scheduler.start()
            app.tick(2)
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["target_coordinate"]["schedule_id"], "coordinate-departure")
            self.assertEqual((train["target_coordinate"]["from_node"], train["target_coordinate"]["to_node"]), ("b01", "b02"))
            self.assertTrue(any(event["type"] == "schedule_coordinate_targeted" for event in app.state()["events"]))
            app.tick(30)
            motion = next(item for item in app.state()["trains"] if item["id"] == "t1")["motion"]
            self.assertAlmostEqual(motion["position"], train["target_coordinate"]["progress"], places=6)
            self.assertEqual(motion["speed"], 0)
        finally:
            app.close()

    def test_http_state_and_command_round_trip(self) -> None:
        app = ControllerApplication.sample()
        server = make_server("127.0.0.1", 0, app)
        app.stop_motion_clock()  # Explicit stepping assertions use a fixed clock.
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/state"
            with urllib.request.urlopen(url, timeout=2) as response:
                state = json.loads(response.read())
            self.assertTrue(state["simulation_mode"])
            self.assertEqual(len(state["trains"]), 2)
            self.assertEqual(state["scans"][0]["id"], "sample-yard")

            payload = json.dumps({"type": "speed", "train_id": "train-3", "speed": 35}).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/commands",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                changed = json.loads(response.read())
            train = next(item for item in changed["trains"] if item["id"] == "t2")
            self.assertEqual(train["speed"], 35)

            add_payload = json.dumps({"type": "add_block", "block": {"id": "B05", "name": "New section"}}).encode()
            add_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/commands",
                data=add_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(add_request, timeout=2) as response:
                added = json.loads(response.read())
            self.assertTrue(any(item["id"] == "b05" for item in added["layout"]["blocks"]))

            tick_payload = json.dumps({"seconds": 60, "rate": 5}).encode()
            tick_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/simulation/tick",
                data=tick_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(tick_request, timeout=2) as response:
                ticked = json.loads(response.read())
            self.assertEqual(ticked["tick"], 3000)
            self.assertEqual(ticked["simulation"]["elapsed_seconds"], 300)
            self.assertEqual(ticked["simulation"]["clock"], "00:05:00")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_commands_project_through_typed_domain_event_controller(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "speed", "train_id": "train-3", "speed": 25})
            app.command({"type": "set_signal", "signal_id": "S01", "aspect": "yellow"})
            app.command({"type": "update_block", "block_id": "B02", "block": {"name": "Platform throat"}})
            app.tick(50)
            events = app.state()["events"]
            self.assertTrue(any(event["type"] == "train_speed_changed" and event["train_id"] == "train-3" for event in events))
            self.assertTrue(any(event["type"] == "signal_aspect_changed" and event["aspect"] == "yellow" for event in events))
            self.assertTrue(any(event["type"] == "block_state_changed" and event["block_id"] == "B02" for event in events))
            self.assertTrue(any(event["type"] == "train_position_changed" and event["to_block_id"] == "B02" for event in events))
            sequences = [event["sequence"] for event in events if "sequence" in event]
            self.assertEqual(sequences, sorted(sequences))
        finally:
            app.close()

    def test_editor_state_is_saved_and_loaded_through_runtime_repository(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "move_block", "block_id": "B01", "x": 275, "y": 190})
            saved = app.save_layout("yard", name="West yard")
            self.assertEqual(saved["name"], "West yard")
            self.assertEqual([record.layout_id for record in app.runtime.layout_repository.list()], ["yard"])
            app.command({"type": "move_block", "block_id": "B01", "x": 5, "y": 5})
            app.load_layout("yard")
            block = next(item for item in app.state()["layout"]["blocks"] if item["id"] == "b01")
            self.assertEqual((block["x"], block["y"]), (275.0, 190.0))
            self.assertEqual(app.runtime.layout.graph().node("B01").position.x, 275.0)
        finally:
            app.close()

    def test_layout_http_endpoints_use_the_runtime_repository(self) -> None:
        app = ControllerApplication.sample()
        server = make_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/api/layouts"
            payload = json.dumps({"layout_id": "api-yard", "name": "API yard"}).encode()
            request = urllib.request.Request(base, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=2) as response:
                saved = json.loads(response.read())
            self.assertEqual(saved["layout_id"], "api-yard")
            with urllib.request.urlopen(base, timeout=2) as response:
                listed = json.loads(response.read())
            self.assertEqual(listed["layouts"][0]["layout_id"], "api-yard")
            with urllib.request.urlopen(f"{base}/api-yard", timeout=2) as response:
                loaded = json.loads(response.read())
            self.assertEqual(len(loaded["layout"]["blocks"]), 4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.close()

    def test_operational_entities_and_train_database_are_exposed(self) -> None:
        app = ControllerApplication.sample()
        try:
            state = app.state()
            layout = state["layout"]
            self.assertEqual(len(layout["signals"]), 2)
            self.assertEqual(len(layout["waypoints"]), 1)
            self.assertEqual(len(layout["turntables"]), 1)
            self.assertEqual(len(layout["platforms"]), 2)
            self.assertEqual(app.train_database("train-101")["decoder_address"], 101)

            app.command({"type": "set_signal", "signal_id": "S01", "aspect": "yellow"})
            app.command({"type": "align_turntable", "turntable_id": "TT01", "block_id": "B04"})
            app.trains[1]["block_id"] = "B04"
            app.trains[1]["speed"] = 0
            app.blocks[2]["status"] = "free"
            app.blocks[2]["occupied_by"] = None
            app._sync_runtime_from_ui()
            app.runtime.dispatcher.tick()
            app.command({"type": "track_power", "enabled": False})
            changed = app.state()["layout"]
            self.assertEqual(changed["signals"][0]["aspect"], "yellow")
            self.assertEqual(changed["turntables"][0]["aligned_block_id"], "B04")
            self.assertFalse(app.runtime.track.get_snapshot().powered)
            self.assertEqual(app.runtime.interlocking.locks, {"T01": "train-101"})
            with self.assertRaisesRegex(ValueError, "turnout is locked"):
                app.command({"type": "set_turnout", "turnout_id": "T01", "state": "diverging"})
        finally:
            app.close()

    def test_layout_asset_crud_normalizes_ids_and_validates_references(self) -> None:
        app = ControllerApplication.sample()
        try:
            added = app.command({
                "type": "add_station",
                "station": {"id": "st03", "name": "Yard", "blockIds": ["b04"]},
            })
            self.assertTrue(any(item["id"] == "ST03" for item in added["layout"]["stations"]))
            updated = app.command({"type": "update_station", "station_id": "st03", "station": {"name": "Yard station"}})
            self.assertEqual(next(item for item in updated["layout"]["stations"] if item["id"] == "ST03")["name"], "Yard station")

            app.command({
                "type": "add_signal",
                "signal": {"id": "s03", "name": "Yard entry", "block_id": "b04", "protects_block_id": "b03"},
            })
            app.command({"type": "update_signal", "signal_id": "s03", "signal": {"name": "Yard signal"}})
            self.assertEqual(next(item for item in app.state()["layout"]["signals"] if item["id"] == "S03")["name"], "Yard signal")

            app.command({
                "type": "add_turnout",
                "turnout": {"id": "t02", "name": "Yard turnout", "from": "b02", "to": "b03", "alternate": "b04"},
            })
            app.command({"type": "remove_turnout", "turnout_id": "t02"})

            app.command({"type": "add_waypoint", "waypoint": {"id": "wp02", "connected_node_ids": ["b04", "tt01"]}})
            app.command({"type": "update_waypoint", "waypoint_id": "wp02", "waypoint": {"name": "Yard point"}})
            app.command({"type": "add_turntable", "turntable": {"id": "tt02", "connected_block_ids": ["b04"], "aligned_block_id": "b04"}})
            app.command({"type": "update_turntable", "turntable_id": "tt02", "turntable": {"name": "Second table"}})
            app.command({
                "type": "add_platform",
                "platform": {"id": "p03", "name": "Yard platform", "stationId": "st03", "blockId": "b04", "lengthMm": 1000},
            })
            platform = app.command({"type": "update_platform", "platform_id": "p03", "platform": {"lengthMm": 1200}})
            self.assertEqual(next(item for item in platform["layout"]["platforms"] if item["id"] == "P03")["lengthMm"], 1200.0)

            with self.assertRaises(ValueError):
                app.command({"type": "add_signal", "signal": {"id": "bad", "block_id": "missing", "protects_block_id": "b04"}})
            self.assertFalse(any(item["id"] == "BAD" for item in app.state()["layout"]["signals"]))
            with self.assertRaises(ValueError):
                app.command({"type": "add_platform", "platform": {"id": "bad-platform", "stationId": "missing", "blockId": "b04"}})
            with self.assertRaises(ValueError):
                app.command({"type": "remove_platform", "platform_id": "p01"})
            self.assertTrue(any(item["id"] == "P01" for item in app.state()["layout"]["platforms"]))

            for asset_type, asset_id in (("signal", "s03"), ("waypoint", "wp02"), ("turntable", "tt02"), ("platform", "p03"), ("station", "st03")):
                result = app.command({"type": f"remove_{asset_type}", f"{asset_type}_id": asset_id})
                self.assertFalse(any(item["id"] == asset_id.upper() for item in result["layout"][f"{asset_type}s"]))
        finally:
            app.close()

    def test_timetable_commands_reach_scheduler_simulation(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "add_schedule", "schedule": {"id": "s3", "time": "00:01", "service": "Test", "number": "101", "platform": "P01"}})
            app.runtime.scheduler.reset(tick=0)
            app.runtime.scheduler.start()
            app.tick(2)
            schedule = next(item for item in app.state()["schedules"] if item["id"] == "s3")
            self.assertEqual(schedule["state"], "Departed")
            self.assertTrue(any(event["type"] == "schedule_departure" for event in app.state()["events"]))
        finally:
            app.close()

    def test_multi_stop_schedule_is_preserved_and_simulated_per_stop(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({
                "type": "add_schedule",
                "schedule": {
                    "id": "multi",
                    "time": "00:01",
                    "service": "Two station test",
                    "number": "101",
                    "train_id": "t1",
                    "station_id": "ST01",
                    "platform": "P01",
                    "origin": "Central station",
                    "destination": "East platform",
                    "route": "Central station  →  East platform",
                    "stops": [
                        {"station_id": "ST01", "platform_id": "P01", "arrival_seconds": 60, "departure_seconds": 120},
                        {"station_id": "ST02", "platform_id": "P02", "arrival_seconds": 180, "departure_seconds": 240},
                    ],
                },
            })
            self.assertEqual([stop.stop_id for stop in app.runtime.scheduler.stops if stop.stop_id.startswith("multi")], ["multi", "multi#1"])
            stored = next(item for item in app.state()["schedules"] if item["id"] == "multi")
            self.assertEqual(len(stored["stops"]), 2)
            app.runtime.scheduler.reset(tick=0)
            app.runtime.scheduler.start()
            app.tick(3)
            self.assertTrue(any(event["type"] == "schedule_arrival" and event["schedule_id"] == "multi" for event in app.state()["events"]))
            self.assertTrue(any(event["type"] == "schedule_arrival" and event["stop_id"] == "multi#1" for event in app.state()["events"]))
        finally:
            app.close()

    def test_schedule_simulation_advances_to_and_updates_next_event(self) -> None:
        app = ControllerApplication.sample()
        try:
            result = app.command({"type": "simulate_schedule"})
            self.assertEqual(app.runtime.scheduler.current_tick, 645)
            self.assertEqual(next(item for item in result["schedules"] if item["id"] == "s1")["state"], "Arrived")
            result = app.command({"type": "simulate_schedule"})
            self.assertEqual(app.runtime.scheduler.current_tick, 646)
            self.assertEqual(next(item for item in result["schedules"] if item["id"] == "s1")["state"], "Departed")
        finally:
            app.close()

    def test_default_layout_is_restored_on_next_application_start(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database_path = f"{folder}/controller.sqlite3"
            first = ControllerApplication.sample(database_path=database_path)
            first.command({"type": "move_block", "block_id": "B01", "x": 333, "y": 211})
            first.save_layout("default", name="Persistent yard")
            first.close()

            second = ControllerApplication.sample(database_path=database_path)
            try:
                block = next(item for item in second.state()["layout"]["blocks"] if item["id"] == "b01")
                self.assertEqual((block["x"], block["y"]), (333.0, 211.0))
                self.assertEqual(second.layout_name, "Persistent yard")
            finally:
                second.close()

    def test_train_profiles_can_be_added_and_persisted_in_model_database(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "add_train", "train": {"id": "train-new", "name": "Shunter", "address": 77, "block_id": "B04", "manufacturer": "Roco", "model_number": "70001", "maxSpeed": 80}})
            record = app.train_database("train-new")
            self.assertEqual(record["decoder_address"], 77)
            self.assertEqual(record["manufacturer"], "Roco")
            self.assertTrue(any(item["id"] == "train-new" for item in app.state()["trains"]))
            app.command({
                "type": "update_consist",
                "train_id": "train-new",
                "consist": [{"id": "coach-1", "type": "coach", "name": "I11 B", "length_mm": 264}],
            })
            record = app.train_database("train-new")
            self.assertEqual(record["rolling_stock"][0]["vehicle_id"], "coach-1")
            self.assertEqual(record["rolling_stock"][0]["length_mm"], 264.0)
        finally:
            app.close()

    def test_calibration_runs_bounded_stop_and_records_measurement(self) -> None:
        app = ControllerApplication.sample()
        try:
            result = app.command({"type": "start_calibration", "train_id": "t2"})
            self.assertEqual(result["calibration"]["active"]["status"], "running")
            deadline = time.monotonic() + 2
            while app.calibration_state()["active"]["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(app.calibration_state()["active"]["status"], "completed")
            result = app.command({"type": "record_calibration", "distance_mm": 37.5, "notes": "Test bench"})
            self.assertEqual(result["calibration"]["active"]["status"], "recorded")
            self.assertEqual(app.calibration_state()["history"][0]["measured_distance_mm"], 37.5)
        finally:
            app.close()

    def test_explicit_speed_resumes_safe_stopped_train_and_stop_command_halts_it(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "set_train_mode", "train_id": "t1", "mode": "stopped"})
            app.command({"type": "set_speed", "train_id": "t1", "speed": 35})
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["mode"], "manual")
            self.assertEqual(train["speed"], 35)
            app.command({"type": "stop_train", "train_id": "t1"})
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["speed"], 0)
            self.assertTrue(all(state.desired_speed == 0 for state in app.runtime.dispatcher.trains.values()))
        finally:
            app.close()

    def test_paired_locomotives_share_motion_commands(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.command({"type": "set_train_mode", "train_id": "t1", "mode": "manual"})
            app.command({"type": "update_consist", "train_id": "t1", "consist": [], "locomotive_ids": ["t2"]})
            state = app.state()
            lead = next(item for item in state["trains"] if item["id"] == "t1")
            self.assertEqual(lead["locomotive_ids"], ["t2"])

            app.command({"type": "stop_train", "train_id": "t1"})
            raw_trains = {item["id"]: item for item in app.trains}
            app.command({"type": "set_direction", "train_id": "t1", "direction": "reverse"})
            self.assertEqual(raw_trains["train-101"]["direction"], "reverse")
            self.assertEqual(raw_trains["train-3"]["direction"], "reverse")

            app.command({"type": "speed", "train_id": "t1", "speed": 30})
            self.assertEqual(raw_trains["train-101"]["speed"], 30)
            self.assertEqual(raw_trains["train-3"]["speed"], 30)

            app.command({"type": "stop_train", "train_id": "t2"})
            self.assertEqual(raw_trains["train-101"]["speed"], 0)
            self.assertEqual(raw_trains["train-3"]["speed"], 0)
        finally:
            app.close()

    def test_train_database_detail_commands_are_persisted_and_evented(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({
                "type": "update_decoder_function",
                "train_id": "t1",
                "function": {"function_number": 2, "name": "Horn", "description": "Long horn", "momentary": True},
            })
            record = app.train_database("train-101")
            self.assertEqual(record["decoder_functions"][0]["name"], "Horn")
            self.assertTrue(record["decoder_functions"][0]["momentary"])

            created = app.command({
                "type": "add_maintenance",
                "train_id": "t1",
                "maintenance": {
                    "service_date": "2026-09-11",
                    "service_type": "inspection",
                    "description": "Routine inspection",
                    "mileage_km": 12.5,
                    "performed_by": "Workshop",
                },
            })
            self.assertEqual(created["trains"][0]["id"], "t1")
            record = app.train_database("t1")
            maintenance_id = record["maintenance_records"][0]["record_id"]
            self.assertEqual(record["maintenance_records"][0]["service_type"], "inspection")
            self.assertTrue(any(event["type"] == "train_database_changed" and event["entity"] == "maintenance" for event in app.state()["events"]))

            app.command({
                "type": "update_maintenance",
                "train_id": "t1",
                "maintenance": {"record_id": maintenance_id, "service_date": "2026-09-11", "service_type": "repair", "description": "Replaced coupler"},
            })
            self.assertEqual(app.train_database("t1")["maintenance_records"][0]["service_type"], "repair")
            app.command({"type": "delete_maintenance", "train_id": "t1", "record_id": maintenance_id})
            app.command({"type": "delete_decoder_function", "train_id": "t1", "function_number": 2})
            self.assertEqual(app.train_database("t1")["decoder_functions"], [])
            self.assertEqual(app.train_database("t1")["maintenance_records"], [])
        finally:
            app.close()

    def test_train_and_assembled_lengths_remain_exact_millimetres(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "update_train", "train_id": "t1", "train": {"length_mm": 1523.75}})
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["length_mm"], 1523.75)
            self.assertEqual(train["length"], 1523.75)

            app.command({
                "type": "update_consist",
                "train_id": "t1",
                "consist": [
                    {"id": "coach-a", "type": "coach", "name": "Coach A", "length_mm": 101.25},
                    {"id": "coach-b", "type": "coach", "name": "Coach B", "length_mm": 202.5},
                ],
                "length_mm": 303.75,
            })
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["length_mm"], 303.75)
            record = app.train_database("train-101")
            self.assertEqual(record["length_mm"], 303.75)
            self.assertEqual(record["rolling_stock"][0]["length_mm"], 101.25)
        finally:
            app.close()

    def test_photo_scan_command_and_layout_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database_path = f"{folder}/controller.sqlite3"
            app = ControllerApplication.sample(database_path=database_path)
            app.command({"type": "add_scan", "scan": {"id": "yard-front", "label": "Yard front", "image": "scans/yard.jpg", "anchor": {"x": 0.2, "y": 0.8}}})
            app.save_layout("default", name="Scanned yard")
            app.close()
            restored = ControllerApplication.sample(database_path=database_path)
            try:
                scan = next(item for item in restored.state()["scans"] if item["id"] == "yard-front")
                self.assertEqual(scan["image"], "scans/yard.jpg")
                self.assertEqual(scan["anchor"], {"x": 0.2, "y": 0.8})
            finally:
                restored.close()

    def test_graph_connections_are_editable_and_feed_the_layout_graph(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "update_block", "block_id": "b01", "block": {"name": "Departure throat", "length_mm": 1250, "station": "West yard"}})
            updated = next(item for item in app.state()["layout"]["blocks"] if item["id"] == "b01")
            self.assertEqual(updated["name"], "Departure throat")
            self.assertEqual(updated["length_mm"], 1250.0)
            app.command({"type": "disconnect_blocks", "from_block_id": "B02", "to_block_id": "B03"})
            self.assertNotIn("B03", app.runtime.layout.snapshot().snapshot.block("B02").neighbor_ids)
            app.command({"type": "connect_blocks", "from_block_id": "B02", "to_block_id": "B04"})
            self.assertIn("B04", app.runtime.layout.snapshot().snapshot.block("B02").neighbor_ids)
            self.assertIn("B02", {edge.target_id for edge in app.runtime.layout.graph().neighbors("B04")})
        finally:
            app.close()

    def test_topology_change_replans_an_automatic_train_route(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "disconnect_blocks", "from_block_id": "B01", "to_block_id": "B02"})
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["route"], ["B01"])
            self.assertEqual(train["speed"], 0)
            self.assertEqual(app.runtime.route_updater.desired_routes["train-101"], ("B01",))
        finally:
            app.close()

    def test_plan_route_uses_layout_graph_and_constant_reservation(self) -> None:
        app = ControllerApplication.sample()
        try:
            result = app.command({"type": "plan_route", "train_id": "t1", "destination_block_id": "B04"})
            train = next(item for item in result["trains"] if item["id"] == "t1")
            self.assertEqual(train["route"], ["B01", "B02", "B03", "B04"])
            self.assertEqual(app.runtime.route_updater.desired_routes["train-101"], ("B01", "B02", "B03", "B04"))
        finally:
            app.close()

    def test_pinboard_can_place_a_stopped_train_between_connection_nodes(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            state = app.command({"type": "place_train_on_track", "train_id": "train-3", "x": 515, "y": 150})
            train = next(item for item in state["trains"] if item["id"] == "t2")
            self.assertEqual(train["position"], "B02")
            self.assertEqual(train["motion"]["from_block_id"], "b02")
            self.assertEqual(train["motion"]["to_block_id"], "b03")
            self.assertGreater(train["motion"]["position"], 0)
            self.assertTrue(any(event["type"] == "train_placed_on_track" for event in state["events"]))
        finally:
            app.close()

    def test_calibrated_pinboard_target_reserves_a_clear_multi_block_route(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            # Free B01 so train-3 can safely travel from B03 through B02 to a
            # coordinate on the B01--B02 segment.
            app.runtime.track.remove_train("train-101")
            app.trains = [train for train in app.trains if train["id"] != "train-101"]
            app.runtime.train_database.add_calibration(
                "train-3", speed_kmh=10, duration_ms=100, measured_distance_mm=50,
                created_at="2026-01-01T00:00:00Z",
            )
            app.command({"type": "stop_train", "train_id": "train-3"})
            app.command({"type": "set_direction", "train_id": "train-3", "direction": "reverse"})
            state = app.command({"type": "move_train_to_coordinate", "train_id": "train-3", "x": 265, "y": 150})
            train = next(item for item in state["trains"] if item["id"] == "t2")
            target = train["target_coordinate"]
            self.assertEqual(target["route_node_ids"], ["b03", "b02", "b01"])
            self.assertEqual(train["route"], ["b03", "b02", "b01"])
            self.assertGreater(target["estimated_duration_ms"], 0)
        finally:
            app.close()

    def test_presence_keeps_station_known_fallback_out_of_physical_detected_count(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.simulation_mode = False
            app.runtime.track.probe_train_address = lambda _address: CommandResult(
                True, "probe_loco_info", "Z21 locomotive information received"
            )
            presence = app.scan_train_presence()
            self.assertTrue(presence["results"])
            self.assertTrue(all(item["response"]["known_to_station"] for item in presence["results"] if item["dcc_address"] is not None))
            self.assertTrue(all(item["detected"] is False for item in presence["results"] if item["dcc_address"] is not None))
            self.assertEqual(presence["summary"]["detected"], 0)
        finally:
            app.close()

    def test_presence_command_returns_immediately_and_finishes_in_background(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            app.simulation_mode = False
            app.trains[0]["address"] = 7

            def slow_station_probe(_address: int) -> CommandResult:
                time.sleep(0.2)
                return CommandResult(True, "probe_loco_info", "station knows address")

            app.runtime.track.probe_train_address = slow_station_probe
            started_at = time.monotonic()
            started = app.command({"type": "scan_train_presence"})
            self.assertLess(time.monotonic() - started_at, 0.15)
            self.assertTrue(started["presence"]["running"])
            deadline = time.monotonic() + 2
            while app.train_presence_state()["running"] and time.monotonic() < deadline:
                time.sleep(0.02)
            completed = app.train_presence_state()
            self.assertFalse(completed["running"])
            self.assertIsNotNone(completed["completed_at"])
            self.assertIsNone(completed["error"])
        finally:
            app.close()

    def test_saved_route_crud_replans_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database_path = f"{folder}/controller.sqlite3"
            app = ControllerApplication.sample(database_path=database_path)
            try:
                added = app.command({"type": "add_route", "route": {"id": "yard-central", "name": "Yard to Central", "source_block_id": "B04", "target_block_id": "B02", "algorithm": "bfs"}})
                saved = next(item for item in added["routes"] if item["id"] == "yard-central")
                self.assertEqual(saved["node_ids"], ["B04", "B03", "B02"])
                self.assertEqual(saved["algorithm"], "bfs")
                app.command({"type": "update_route", "route_id": "yard-central", "route": {"name": "Yard to Central (A*)", "algorithm": "a_star"}})
                app.command({"type": "apply_route", "route_id": "yard-central", "train_id": "t2"})
                train = next(item for item in app.state()["trains"] if item["id"] == "t2")
                self.assertEqual(train["route"], ["B04", "B03", "B02"])
                self.assertEqual(train["destination_block_id"], "B02")
                app.save_layout("default")
            finally:
                app.close()
            restored = ControllerApplication.sample(database_path=database_path)
            try:
                route = next(item for item in restored.routes if item["id"] == "yard-central")
                self.assertEqual(route["name"], "Yard to Central (A*)")
                restored.command({"type": "remove_route", "route_id": "yard-central"})
                self.assertNotIn("yard-central", [item["id"] for item in restored.routes])
            finally:
                restored.close()

    def test_train_profile_persists_explicit_destination_block(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "update_train", "train_id": "t1", "train": {"destination": "Yard", "destination_block_id": "b04"}})
            train = next(item for item in app.state()["trains"] if item["id"] == "t1")
            self.assertEqual(train["destination_block_id"], "B04")
            planned = app.command({"type": "plan_route", "train_id": "t1", "destination_block_id": train["destination_block_id"]})
            self.assertEqual(next(item for item in planned["trains"] if item["id"] == "t1")["route"][-1], "B04")
        finally:
            app.close()

    def test_safe_stop_mode_stops_all_simulated_trains(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "set_mode", "mode": "stopped"})
            self.assertTrue(all(item["speed"] == 0 for item in app.state()["trains"]))
            self.assertTrue(all(motion.target_speed == 0 for motion in app.runtime.track.get_snapshot().trains))
        finally:
            app.close()

    def test_authored_automation_program_compiles_timed_blocks_and_runs(self) -> None:
        app = ControllerApplication.sample()
        app.stop_motion_clock()
        try:
            saved = app.command({
                "type": "save_automation_program",
                "program": {
                    "id": "platform-arrival",
                    "name": "Platform arrival",
                    "train_id": "t2",
                    "blocks": [
                        {"type": "drive", "speed_kmh": 10, "duration_s": 0.01},
                        {"type": "function", "function_number": 0, "enabled": False},
                    ],
                },
            })
            program = next(item for item in saved["automationPrograms"] if item["id"] == "platform-arrival")
            self.assertEqual(program["train_id"], "t2")
            self.assertEqual(program["duration_s"], 0.01)
            self.assertNotIn("_compiled_actions", program)

            ran = app.command({"type": "play_automation_program", "program_id": "platform-arrival", "automatic": True, "confirm": True})
            train = next(item for item in ran["trains"] if item["id"] == "t2")
            self.assertEqual(train["speed"], 0)
            self.assertFalse(train["decoder_function_states"]["0"])

            deleted = app.command({"type": "delete_automation_program", "program_id": "platform-arrival"})
            self.assertEqual(deleted["automationPrograms"], [])
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
