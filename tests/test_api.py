"""Smoke tests for the dependency-free HTTP application boundary."""

from __future__ import annotations

import json
import threading
import tempfile
import unittest
import urllib.request

from backend.api.server import ControllerApplication, make_server


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


if __name__ == "__main__":
    unittest.main()
