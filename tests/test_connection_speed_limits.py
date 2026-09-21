"""Connection rule persistence, traversal and safety regressions (no hardware)."""
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import Mock

from backend.api.server import ControllerApplication, make_server
from backend.core.models import ConnectionSpeedLimit
from backend.infrastructure.interfaces import CommandResult
from backend.infrastructure.interfaces import ConnectionStatus, ConnectionState
from backend.runtime import ControllerRuntime
from backend.services.connection import ConnectionChecker
from backend.infrastructure.layout_repository import snapshot_from_dict, snapshot_to_dict
from backend.infrastructure.real_track import Z21TrackSystem
from backend.infrastructure.simulation import SimulatedTrackSystem
from backend.services.connection_speed import ConnectionSpeedPolicy
from backend.services.dispatcher import ControlMode, Dispatcher


def app_fixture(database_path=":memory:", mode="manual"):
    return ControllerApplication(
        blocks=[{"id": key, "neighbor_ids": neighbors, "length_mm": 1000}
                for key, neighbors in (("A", ["B"]), ("B", ["A", "C"]), ("C", ["B"]))],
        trains=[{"id": "engine", "name": "Engine", "address": 7, "block_id": "A",
                 "route": ["A", "B", "C"], "mode": mode, "speed": 0, "maxSpeed": 100}],
        turnouts=[], schedules=[], scans=[], database_path=database_path)


class ConnectionApiTests(unittest.TestCase):
    def setUp(self):
        self.app = app_fixture()
        self.addCleanup(self.app.close)

    def limit(self, **kwargs):
        return self.app.command({"type": "set_connection_speed_limit", "from": "a", "to": "b", **kwargs})

    def test_physical_train_address_edit_rebinds_live_z21_track(self):
        transport = Mock()
        connected = ConnectionStatus(ConnectionState.CONNECTED, "fake-z21")
        transport.check_connection.return_value = connected
        transport.connection_status.return_value = connected
        transport.send_dataset.return_value = CommandResult(True, "z21", "accepted")
        track = Z21TrackSystem(transport)
        runtime = ControllerRuntime._compose(track, database_path=":memory:", connection=ConnectionChecker(track))
        app = ControllerApplication(
            runtime=runtime,
            z21_host="fake-z21",
            simulation_mode=False,
            blocks=[{"id": "A", "neighbor_ids": ["B"]}, {"id": "B", "neighbor_ids": ["A"]}],
            trains=[{"id": "engine", "name": "Engine", "address": None, "block_id": "A", "mode": "manual", "speed": 0}],
            turnouts=[], schedules=[],
        )
        try:
            self.assertNotIn("engine", track._train_addresses)
            app.command({"type": "update_train", "train_id": "engine", "train": {"number": "7"}})
            self.assertEqual(track._train_addresses["engine"], 7)
            app.command({"type": "set_train_mode", "train_id": "engine", "mode": "manual"})
            app.command({"type": "track_power", "enabled": True})
            result = app.command({"type": "set_speed", "train_id": "engine", "speed": 30})
            self.assertEqual(result["trains"][0]["requested_speed_kmh"], 30)
            self.assertTrue(transport.send_dataset.called)
        finally:
            app.close()

    def test_scheduled_saved_route_departure_sends_physical_movement(self):
        transport = Mock()
        connected = ConnectionStatus(ConnectionState.CONNECTED, "fake-z21")
        transport.check_connection.return_value = connected
        transport.connection_status.return_value = connected
        transport.send_dataset.return_value = CommandResult(True, "z21", "accepted")
        track = Z21TrackSystem(transport)
        runtime = ControllerRuntime._compose(track, database_path=":memory:", connection=ConnectionChecker(track))
        app = ControllerApplication(
            runtime=runtime,
            z21_host="fake-z21",
            simulation_mode=False,
            blocks=[{"id": "A", "neighbor_ids": ["B"]}, {"id": "B", "neighbor_ids": ["A"]}],
            trains=[{"id": "engine", "name": "Engine", "address": 7, "block_id": "A", "mode": "stopped", "speed": 0}],
            turnouts=[], schedules=[],
            routes=[{"id": "route-1", "name": "Yard route", "node_ids": ["A", "B"], "enabled": True}],
        )
        try:
            app.stop_motion_clock()
            app.command({"type": "track_power", "enabled": True})
            app.command({"type": "add_schedule", "schedule": {
                "id": "physical-route-departure", "time": "00:01", "service": "Yard move",
                "number": "7", "train_id": "engine", "station_id": "ST01",
                "dispatch_mode": "route", "route_id": "route-1",
            }})
            app.runtime.scheduler.reset(tick=0)
            app.runtime.scheduler.start()
            transport.reset_mock()
            app.tick(2)
            movement_packets = [
                call for call in transport.send_dataset.call_args_list
                if call.kwargs.get("command") == "set_loco_drive"
            ]
            self.assertTrue(movement_packets, "scheduled departure did not send a Z21 movement packet")
            self.assertGreater(track.get_effective_speed("engine"), 0)
            self.assertEqual(app.state()["trains"][0]["scheduled_route_id"], "route-1")
        finally:
            app.close()
    def test_default_override_and_clear_are_directed(self):
        self.limit(speed_limit_kmh=40)
        state = self.limit(train_id="engine", speed_limit_kmh=20)
        forward = next(c for c in state["layout"]["connections"] if (c["from"], c["to"]) == ("a", "b"))
        reverse = next(c for c in state["layout"]["connections"] if (c["from"], c["to"]) == ("b", "a"))
        self.assertEqual(forward["train_speed_limits"], {"engine": 20})
        self.assertIsNone(reverse["speed_limit_kmh"])
        self.app.command({"type": "set_speed", "train_id": "engine", "speed": 80})
        state = self.app.state()["trains"][0]
        self.assertEqual(state["requested_speed_kmh"], 80)
        self.assertEqual(state["effective_speed_kmh"], 20)
        self.assertEqual(state["motion"]["to_block_id"], "b")
        self.assertEqual(state["motion"]["position"], 0)
        self.limit(train_id="engine", speed_limit_kmh=None)
        self.assertEqual(self.app.state()["trains"][0]["effective_speed_kmh"], 40)
        self.limit(speed_limit_kmh=None)
        self.assertEqual(self.app.state()["trains"][0]["effective_speed_kmh"], 80)

    def test_invalid_rules_do_not_mutate(self):
        for value in (-1, float("nan"), float("inf"), True, "fast"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.limit(speed_limit_kmh=value)
            self.assertEqual(self.app.connection_limits, [])
        for extra in ({"to": "c", "speed_limit_kmh": 10},
                      {"train_id": "missing", "speed_limit_kmh": 10},
                      {"train_speed_limits": {"missing": 10}},
                      {"train_speed_limits": []}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.limit(**extra)
            self.assertEqual(self.app.connection_limits, [])

    def test_limits_and_requested_speed_round_trip(self):
        self.limit(speed_limit_kmh=20, train_speed_limits={"engine": 30})
        self.app.command({"type": "set_speed", "train_id": "engine", "speed": 80})
        self.app.tick(1)
        snapshot = self.app._domain_snapshot()
        self.assertEqual(snapshot_from_dict(snapshot_to_dict(snapshot)), snapshot)
        self.app.save_layout("limits")
        self.app.connection_limits = []
        self.app.load_layout("limits")
        train = self.app.state()["trains"][0]
        self.assertEqual(train["requested_speed_kmh"], 80)
        self.assertEqual(train["effective_speed_kmh"], 30)

    def test_stopped_save_restart_does_not_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "controller.sqlite3")
            first = app_fixture(database)
            try:
                first.command({"type": "set_connection_speed_limit", "from": "a", "to": "b", "speed_limit_kmh": 25})
                first.command({"type": "set_speed", "train_id": "engine", "speed": 80})
                first.command({"type": "track_power", "enabled": False})
                first.save_layout("native-switch")
            finally:
                first.close()
            second = app_fixture(database)
            try:
                second.load_layout("native-switch")
                second.command({"type": "track_power", "enabled": True})
                second.tick(5)
                train = second.state()["trains"][0]
                self.assertEqual(train["mode"], "stopped")
                self.assertEqual(train["requested_speed_kmh"], 0)
                self.assertEqual(train["actual_speed_kmh"], 0)
                self.assertEqual(second.connection_limits[0]["speed_limit_kmh"], 25)
                second.command({"type": "set_train_mode", "train_id": "engine", "mode": "manual"})
                self.assertEqual(second.state()["trains"][0]["requested_speed_kmh"], 0)
            finally:
                second.close()

    def test_rename_and_disconnect_keep_rules_consistent(self):
        self.limit(speed_limit_kmh=20)
        self.app.command({"type": "track_power", "enabled": False})
        self.app.command({"type": "update_block", "block_id": "b", "block": {"id": "yard"}})
        self.assertEqual(self.app.connection_limits[0]["to"], "YARD")
        self.app.command({"type": "disconnect_blocks", "from": "a", "to": "yard"})
        self.assertEqual(self.app.connection_limits, [])
        self.app.save_layout()

    def test_editor_rename_after_train_leaves_saved_occupied_block(self):
        app = ControllerApplication.sample()
        try:
            app.tick(50)
            self.assertEqual(app.trains[0]["block_id"], "B02")
            app.command({"type": "add_block", "block": {}})
            app.command({"type": "track_power", "enabled": False})
            app.command({"type": "update_block", "block_id": "B05", "block": {"id": "TEST-YARD"}})
            app.save_layout()
            self.assertIn("TEST-YARD", {b["id"] for b in app.blocks})
        finally:
            app.close()

    def test_realtime_clock_uses_seconds_and_scheduler_uses_minutes(self):
        for _ in range(20):
            self.app.tick(1, elapsed_seconds=.1)
        state = self.app.state()
        self.assertEqual(state["simulation"]["clock"], "00:00:02")
        self.assertEqual(self.app.runtime.scheduler.current_tick, 0)
        for _ in range(580):
            self.app.tick(1, elapsed_seconds=.1)
        self.assertEqual(self.app.state()["simulation"]["clock"], "00:01:00")
        self.assertEqual(self.app.runtime.scheduler.current_tick, 1)
        self.app.tick(3)  # Explicit legacy timetable fast-forward still deliberate.
        self.assertEqual(self.app.runtime.scheduler.current_tick, 4)

    def test_manual_and_automatic_restore_after_traversal(self):
        for mode in ("manual", "automatic"):
            app = app_fixture(mode=mode)
            try:
                app.command({"type": "set_connection_speed_limit", "from": "a", "to": "b", "speed_limit_kmh": 20})
                app.command({"type": "set_speed", "train_id": "engine", "speed": 80})
                entered = False
                for _ in range(80):
                    app.tick(1)
                    train = app.state()["trains"][0]
                    if train["position"] == "A":
                        self.assertLessEqual(train["actual_speed_kmh"], 20)
                    elif train["position"] == "B":
                        self.assertEqual(train["requested_speed_kmh"], 80)
                        self.assertEqual(train["effective_speed_kmh"], 80)
                        entered = True
                        break
                self.assertTrue(entered, mode)
            finally:
                app.close()

    def test_zero_limit_and_stop_cannot_be_bypassed_by_direction(self):
        self.limit(speed_limit_kmh=0)
        self.app.command({"type": "set_speed", "train_id": "engine", "speed": 80})
        self.app.tick(4)
        self.assertEqual(self.app.state()["trains"][0]["actual_speed_kmh"], 0)
        with self.assertRaisesRegex(ValueError, "stop"):
            self.app.command({"type": "set_direction", "train_id": "engine", "direction": "reverse"})
        self.app.command({"type": "set_speed", "train_id": "engine", "speed": 0})
        self.app.command({"type": "set_direction", "train_id": "engine", "direction": "reverse"})
        self.limit(speed_limit_kmh=None)
        self.app.tick(4)
        self.assertEqual(self.app.state()["trains"][0]["requested_speed_kmh"], 0)

    def test_http_edit_and_shared_clock_lifecycle(self):
        server = make_server("127.0.0.1", 0, self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            worker = self.app._motion_thread
            self.app.start_motion_clock()
            self.assertIs(self.app._motion_thread, worker)
            payload = {"type": "set_connection_speed_limit", "from": "a", "to": "b", "speed_limit_kmh": 15}
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/commands",
                data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(json.load(response)["layout"]["connection_limits"][0]["speed_limit_kmh"], 15)
            self.app.command({"type": "set_speed", "train_id": "engine", "speed": 80})
            deadline = time.monotonic() + 2
            while self.app.state()["trains"][0]["motion"]["position"] == 0 and time.monotonic() < deadline:
                threading.Event().wait(.02)
            self.assertGreater(self.app.state()["trains"][0]["motion"]["position"], 0)
            self.app.command({"type": "pause_simulation"})
            before = self.app.runtime.track.get_snapshot()
            threading.Event().wait(.15)
            self.assertEqual(self.app.runtime.track.get_snapshot(), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.assertFalse(worker.is_alive())


class ConnectionAdapterTests(unittest.TestCase):
    def test_reverse_and_train_override(self):
        track = SimulatedTrackSystem()
        track.add_train("train", "B", route=("A", "B", "C"))
        track.configure_speed_limits(ConnectionSpeedPolicy([
            ConnectionSpeedLimit("A", "B", 50), ConnectionSpeedLimit("B", "A", 40, (("train", 10),))], {"train": 100}))
        self.assertTrue(track.set_train_direction("train", forward=False).accepted)
        track.set_train_speed("train", .8)
        motion = track.tick(4).trains[0]
        self.assertEqual(motion.direction, -1)
        self.assertLessEqual(motion.speed, .1)
        self.assertEqual(motion.target_speed, .1)

    def test_crossing_multiple_zones_in_one_tick_never_skips_limit(self):
        track = SimulatedTrackSystem(tick_seconds=3, acceleration=100)
        track.add_train("train", "A", route=("A", "B", "C", "D"))
        track.configure_speed_limits(ConnectionSpeedPolicy([ConnectionSpeedLimit("B", "C", 10)], {"train": 100}))
        track.set_train_speed("train", 1)
        motion = track.tick().trains[0]
        self.assertEqual(motion.block_id, "B")
        self.assertAlmostEqual(motion.position, .2)
        self.assertEqual(motion.speed, .1)

    def test_zero_zone_releases_but_emergency_stop_does_not(self):
        track = SimulatedTrackSystem()
        track.add_train("train", "A", route=("A", "B"))
        dispatcher = Dispatcher(track)
        dispatcher.manual_speed("train", .7)
        track.configure_speed_limits(ConnectionSpeedPolicy([ConnectionSpeedLimit("A", "B", 0)]))
        self.assertEqual(track.tick().trains[0].speed, 0)
        dispatcher.emergency_stop()
        track.configure_speed_limits(ConnectionSpeedPolicy())
        dispatcher.set_mode("train", ControlMode.MANUAL)
        self.assertEqual(track.tick().trains[0].speed, 0)
        self.assertEqual(dispatcher.trains["train"].desired_speed, 0)

    def physical(self):
        transport = Mock()
        transport.send_dataset.return_value = CommandResult(True, "drive")
        track = Z21TrackSystem(transport)
        track.register_train("train", 7)
        track.configure_speed_limits(ConnectionSpeedPolicy([ConnectionSpeedLimit("A", "B", 20)], {"train": 100}))
        return track, transport

    def test_physical_reports_restore_requested_speed_and_keep_direction(self):
        track, transport = self.physical()
        track.report_train_position("train", "A", ("A", "B", "C"))
        track.set_train_speed("train", .8)
        self.assertEqual(track.get_snapshot().trains[0].target_speed, .2)
        self.assertFalse(track.set_train_direction("train", forward=False).accepted)
        track.report_train_position("train", "B", ("A", "B", "C"))
        self.assertEqual(track.get_snapshot().trains[0].target_speed, .8)
        track.stop_train("train")
        self.assertTrue(track.set_train_direction("train", forward=False).accepted)
        before = transport.send_dataset.call_count
        track.report_train_position("train", "C", ("A", "B", "C"))
        self.assertEqual(transport.send_dataset.call_count, before)
        self.assertEqual(track.get_snapshot().trains[0].target_speed, 0)

    def test_physical_decoder_function_is_sent_and_remembered(self):
        track, transport = self.physical()
        result = track.set_train_function("train", 3, enabled=True)
        self.assertTrue(result.accepted)
        self.assertEqual(transport.set_loco_function.call_args.kwargs, {"enabled": True})
        self.assertEqual(transport.set_loco_function.call_args.args, (7, 3))
        self.assertEqual(track.get_train_functions("train"), {3: True})

    def test_physical_unknown_position_conservative_and_failures_do_not_replay(self):
        track, transport = self.physical()
        track.set_train_speed("train", .8)
        self.assertEqual(transport.send_dataset.call_args.args[0][8] & 0x7f, 25)

    def test_physical_startup_and_saved_moving_layout_never_send_motion(self):
        track, transport = self.physical()
        transport.check_connection.return_value = ConnectionStatus(ConnectionState.CONNECTED, "fake-z21")
        transport.connection_status.return_value = transport.check_connection.return_value
        runtime = ControllerRuntime._compose(track, database_path=":memory:", connection=ConnectionChecker(track))
        simulation = app_fixture(mode="automatic")
        try:
            simulation.command({"type": "set_speed", "train_id": "engine", "speed": 80})
            runtime.layout_repository.save("moving", simulation._domain_snapshot())
        finally:
            simulation.close()
        app = ControllerApplication(runtime=runtime, z21_host="fake-z21", simulation_mode=False,
            blocks=[{"id": "A", "neighbor_ids": ["B"]}, {"id": "B", "neighbor_ids": ["A"]}],
            trains=[{"id": "engine", "name": "Engine", "address": 7, "block_id": "A",
                     "mode": "automatic", "speed": 80, "maxSpeed": 100}], turnouts=[], schedules=[])
        try:
            transport.send_dataset.assert_not_called()
            self.assertFalse(app.track_power)
            app.load_layout("moving")
            self.assertEqual(app.state()["trains"][0]["position"], "—")
            self.assertIsNone(app.state()["trains"][0]["motion"]["position"])
            self.assertEqual(app.state()["trains"][0]["motion"]["source"], "unknown")
            self.assertEqual(app.layout_info()["train_count"], 0)
            self.assertFalse(any(block["trainId"] for block in app.state()["layout"]["blocks"]))
            app.command({"type": "track_power", "enabled": True})
            app.start_motion_clock()
            deadline = time.monotonic() + 2
            while app.tick_count == 0 and time.monotonic() < deadline:
                threading.Event().wait(.02)
            self.assertGreater(app.tick_count, 0)
            self.assertEqual(app.runtime.dispatcher.trains["engine"].desired_speed, 0)
            for call in transport.send_dataset.call_args_list:
                if call.kwargs.get("command") in {"set_loco_drive", "stop_train"}:
                    self.assertEqual(call.args[0][8] & 0x7f, 0)
            app.command({"type": "set_train_mode", "train_id": "engine", "mode": "manual"})
            app.command({"type": "set_speed", "train_id": "engine", "speed": 50})
            app.command({"type": "track_power", "enabled": False})
            before = transport.send_dataset.call_count
            threading.Event().wait(1.1)
            self.assertEqual(transport.send_dataset.call_count, before)
            self.assertEqual(app.runtime.dispatcher.trains["engine"].desired_speed, 0)
            with self.assertRaisesRegex(ValueError, "power"):
                app.command({"type": "set_speed", "train_id": "engine", "speed": 50})
        finally:
            app.close()

    def test_physical_failure_clears_motion_targets(self):
        track, transport = self.physical()
        transport.check_connection.return_value = ConnectionStatus(ConnectionState.DISCONNECTED, "fake-z21")
        runtime = ControllerRuntime._compose(track, database_path=":memory:", connection=ConnectionChecker(track))
        try:
            runtime.dispatcher.manual_speed("train", .8)
            runtime.tick()
            self.assertEqual(runtime.dispatcher.trains["train"].desired_speed, 0)
            self.assertEqual(track._requested_speeds["train"], 0)
        finally:
            runtime.close()

    def test_new_limit_caps_unlocated_manual_train_immediately(self):
        track, transport = self.physical()
        track.configure_speed_limits(ConnectionSpeedPolicy())
        track.set_train_speed("train", .8)
        self.assertEqual(track.get_effective_speed("train"), .8)
        track.configure_speed_limits(ConnectionSpeedPolicy([ConnectionSpeedLimit("A", "B", 10)], {"train": 100}))
        self.assertEqual(track.get_effective_speed("train"), .1)
        self.assertEqual(track.get_train_speed_limit("train"), 10)
        self.assertEqual(track.get_snapshot().trains, ())
        self.assertEqual(transport.send_dataset.call_args.args[0][8] & 0x7f, 12)
        transport.send_dataset.return_value = CommandResult(False, "stop", "offline")
        track.stop_train("train")
        self.assertFalse(track.set_train_direction("train", forward=False).accepted)

    def test_failed_physical_limit_command_is_not_replayed_by_position_report(self):
        track, transport = self.physical()
        track.set_train_speed("train", .8)
        transport.send_dataset.return_value = CommandResult(False, "drive", "offline")
        track.report_train_position("train", "B", ("A", "B", "C"))
        before = transport.send_dataset.call_count
        track.report_train_position("train", "C", ("A", "B", "C"))
        self.assertEqual(transport.send_dataset.call_count, before)
        for speed in (float("nan"), -1, 2):
            with self.assertRaises(ValueError):
                track.set_train_speed("train", speed)


if __name__ == "__main__":
    unittest.main()
