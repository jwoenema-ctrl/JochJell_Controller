import json
from pathlib import Path
import queue
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.api.server import ControllerApplication
from backend.infrastructure.computer_feedback import ComputerFeedback
from backend.infrastructure.interfaces import CommandResult
from backend.runtime import ControllerRuntime
from tests.test_hardware_switching import FakePhysicalTrack


class Bridge:
    """A real TCP peer serving both occupancy snapshots and turnout acknowledgements."""
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(.05)
        self.port = self.listener.getsockname()[1]
        self.received = queue.Queue()
        self.mode = "accept"
        self.stop = threading.Event()
        self.peer = None
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    self.peer, _ = self.listener.accept()
                    break
                except socket.timeout:
                    continue
            if self.peer is None:
                return
            self.peer.settimeout(.05)
            buffer = b""
            while not self.stop.is_set():
                self.peer.sendall(b'{"contacts":[{"module":1,"input":1,"occupied":false}]}\n')
                try:
                    chunk = self.peer.recv(8192)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer += chunk
                while b'\n' in buffer:
                    frame, buffer = buffer.split(b'\n', 1)
                    command = json.loads(frame)
                    self.received.put(command)
                    if self.mode == "ignore":
                        continue
                    ack = {key: command[key] for key in ("request_id", "module", "output", "position")}
                    ack.update(type="turnout_ack", accepted=self.mode != "reject", detail="fixture rejection" if self.mode == "reject" else "")
                    if self.mode == "wrong":
                        ack["output"] += 1
                    self.peer.sendall(json.dumps(ack).encode() + b'\n')
        except OSError:
            pass
        finally:
            if self.peer:
                self.peer.close()

    def close(self):
        self.stop.set()
        self.listener.close()
        if self.peer:
            self.peer.close()
        self.worker.join(timeout=.5)


class ComputerTurnoutTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()
        self.app.stop_motion_clock()
        self.addCleanup(self.app.close)
        self.source = self.app._track_trigger_controller.computer
        self.service = self.app._track_trigger_controller.computer_turnouts

    def assign(self, turnout="T01", **updates):
        return self.app.command({"type": "set_turnout_connector", "turnout_id": turnout,
                                 "assignment": {"module": 2, "output": 3, "inverted": False, "pulse_ms": 250, **updates}})

    def connect_station(self):
        self.app.update_settings({"hardware": {"system": "ecos", "host": "127.0.0.1"}})
        track = FakePhysicalTrack()
        with patch.object(ControllerRuntime, "create_track", return_value=track):
            self.app.command({"type": "connect_hardware"})
        return track

    def connect_bridge(self):
        bridge = Bridge()
        self.addCleanup(bridge.close)
        self.source.config.update(transport="tcp", port=bridge.port, timeout_s=.5)
        self.app.command({"type": "connect_computer_feedback"})
        return bridge

    def move(self, position="diverging"):
        return self.app.command({"type": "set_turnout", "turnout_id": "to1", "state": position})

    def test_real_tcp_shared_bridge_ack_and_inverted_output(self):
        self.assign(inverted=True, pulse_ms=400)
        self.app.command({"type": "set_block_feedback", "system": "computer", "block_id": "B04", "contacts": [{"module": 1, "input": 1}]})
        track = self.connect_station()
        bridge = self.connect_bridge()
        self.assertFalse(self.source.healthy, "A connection alone does not confirm switch commands")
        self.move()
        command = bridge.received.get(timeout=1)
        self.assertEqual(command["position"], "straight", "Wiring inversion is applied only on the wire")
        self.assertEqual((command["module"], command["output"], command["pulse_ms"]), (2, 3, 400))
        self.assertEqual(self.app.turnouts[0]["state"], "diverging")
        self.assertEqual(self.source.payload()["switch_states"], {"T01": "diverging"})
        self.assertTrue(track.feedback_healthy)
        self.assertEqual(self.source.occupied_blocks(), {})
        self.assertFalse(any(row[0] == "drive" for row in track.commands), "No station train commands route through the bridge")
        self.move("straight")
        self.assertEqual(bridge.received.get(timeout=1)["position"], "diverging")

    def test_negative_ack_does_not_update_switch_and_protects_movement(self):
        self.assign()
        track = self.connect_station()
        bridge = self.connect_bridge()
        bridge.mode = "reject"
        with self.assertRaisesRegex(ValueError, "fixture rejection"):
            self.move()
        self.assertEqual(self.app.turnouts[0]["state"], "straight")
        self.assertFalse(track.feedback_healthy)
        self.assertFalse(track.set_train_speed_by_address(3, .5).accepted)
        self.assertEqual(bridge.received.qsize(), 1)

    def test_timeout_wrong_ack_no_retry_and_recovery(self):
        self.assign()
        self.connect_station()
        bridge = self.connect_bridge()
        for mode in ("ignore", "wrong"):
            bridge.mode = mode
            with self.assertRaisesRegex(ValueError, "timed out"):
                self.move()
            bridge.received.get(timeout=1)
            self.assertTrue(bridge.received.empty(), "Unconfirmed actuation is never automatically retried")
            self.assertEqual(self.app.turnouts[0]["state"], "straight")
        bridge.mode = "accept"
        self.move()
        self.assertEqual(self.app.turnouts[0]["state"], "diverging")

    def test_serial_output_uses_same_frame_and_ack_matching(self):
        self.assign()
        self.connect_station()
        source = self.source
        frames = []
        class SerialPeer:
            def write(self, wire):
                command = json.loads(wire)
                frames.append(command)
                source.ingest({**{key: command[key] for key in ("request_id", "module", "output", "position")}, "type": "turnout_ack", "accepted": True})
                return len(wire)
            def close(self):
                pass
        source._stream = SerialPeer()
        source._connected = True
        source.ingest({"contacts": []})
        self.move()
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["type"], "set_turnout")
        self.assertTrue(source.healthy)

    def test_route_locked_turnout_never_sends_a_command(self):
        self.assign()
        self.connect_station()
        bridge = self.connect_bridge()
        self.app.runtime.interlocking._locks["T01"] = "T1"
        with self.assertRaisesRegex(ValueError, "locked"):
            self.move()
        self.assertTrue(bridge.received.empty())
        with self.assertRaisesRegex(ValueError, "locked"):
            self.assign(output=4)

    def test_simulation_saves_and_toggles_without_physical_actuation(self):
        with patch.object(self.source, "send_turnout", side_effect=AssertionError("physical actuation")):
            self.assign()
            self.move()
        self.assertEqual(self.app.turnouts[0]["state"], "diverging")
        self.assertFalse(self.source.payload()["connected"])

    def test_disconnect_clears_confirmed_states_and_heartbeat_timeout_protects(self):
        self.assign()
        self.connect_station()
        self.connect_bridge()
        self.move()
        self.assertTrue(self.source.healthy)
        with patch.object(self.source, "_clock", return_value=time.monotonic() + 2):
            self.assertFalse(self.source.healthy)
            self.assertIn("stale", self.source.error)
        self.app.command({"type": "disconnect_computer_feedback"})
        self.assertEqual(self.source.payload()["switch_states"], {})
        with self.assertRaisesRegex(ValueError, "disconnected"):
            self.move()

    def test_invalid_assignment_duplicate_output_and_missing_turnout(self):
        self.assign()
        before = list(self.service.assignments)
        for update in ({"module": True}, {"module": 0}, {"output": 65536}, {"pulse_ms": 20},
                       {"inverted": 1}, {"pulse_ms": 1001}, {"extra": 1}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.assign(**update)
            self.assertEqual(self.service.assignments, before)
        with self.assertRaisesRegex(ValueError, "existing"):
            self.assign("MISSING", output=4)
        self.app.command({"type": "add_turnout", "turnout": {"id": "T02", "from": "B01", "to": "B02", "alternate": "B04", "address": 2}})
        with self.assertRaisesRegex(ValueError, "already assigned"):
            self.assign("T02")

    def test_power_guard_persistence_rollback_and_delete_guard(self):
        self.assign()
        self.connect_station()
        self.app.command({"type": "track_power", "enabled": True})
        with self.assertRaisesRegex(ValueError, "power off"):
            self.assign(output=4)
        self.app.command({"type": "track_power", "enabled": False})
        with patch.object(self.app, "_persist_operating_plan", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.assign(output=4)
        self.assertEqual(self.source.turnouts["T01"]["output"], 3)
        with self.assertRaisesRegex(ValueError, "assignment"):
            self.app.command({"type": "delete_turnout", "turnout_id": "T01"})

    def test_restart_preserves_assignments_without_connection_or_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "app.sqlite3")
            app = ControllerApplication.sample(database_path=path)
            app.command({"type": "set_turnout_connector", "turnout_id": "T01", "assignment": {"module": 2, "output": 3, "inverted": True, "pulse_ms": 250}})
            app.close()
            with patch.object(ComputerFeedback, "connect", side_effect=AssertionError("implicit connect")):
                restored = ControllerApplication.sample(database_path=path)
            try:
                source = restored._track_trigger_controller.computer
                self.assertEqual(source.turnouts["T01"]["output"], 3)
                self.assertFalse(source.payload()["connected"])
                self.assertFalse(source.healthy)
            finally:
                restored.close()

    def test_command_station_fallback_and_rejection_does_not_mutate(self):
        track = self.connect_station()
        with patch.object(track, "set_turnout_by_address", return_value=CommandResult(False, "set_turnout", "station rejected")) as station:
            with self.assertRaisesRegex(ValueError, "station rejected"):
                self.move()
            self.assertEqual(self.app.turnouts[0]["state"], "straight")
            station.assert_called_once_with(1, output=1)
        self.assign()
        self.app.command({"type": "set_turnout_connector", "turnout_id": "T01", "assignment": None})
        with patch.object(track, "set_turnout_by_address", return_value=CommandResult(True, "set_turnout")) as station:
            self.move()
            station.assert_called_once_with(1, output=1)

    def test_unknown_late_ack_cannot_confirm_a_switch(self):
        self.assign()
        self.source.ingest({"type": "turnout_ack", "request_id": "late", "module": 2, "output": 3, "position": "straight", "accepted": True})
        self.assertEqual(self.source.payload()["switch_states"], {})
        self.assertFalse(self.source.healthy)


if __name__ == "__main__":
    unittest.main()
