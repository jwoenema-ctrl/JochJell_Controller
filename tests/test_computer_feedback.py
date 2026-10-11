import json
from pathlib import Path
import queue
import socket
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from backend.api.server import ControllerApplication
from backend.infrastructure.computer_feedback import ComputerFeedback, validate_computer_feedback
from backend.infrastructure.simulation import SimulatedTrackSystem
from backend.runtime import ControllerRuntime
from backend.services.dispatcher import ControlMode
from tests.test_hardware_switching import FakePhysicalTrack


def snapshot(*states):
    return {"contacts": [{"module": 1, "input": index + 1, "occupied": state} for index, state in enumerate(states)]}


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("detector fixture did not reach expected state")


class ComputerFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.source = ComputerFeedback(clock=lambda: self.now)
        self.source.replace_mapping({(1, 1): "B02", (1, 2): "B02"})
        self.source._connected = True
        self.addCleanup(self.source.close)

    def test_occupancy_or_freshness_partial_data_and_recovery(self):
        self.assertFalse(self.source.healthy)
        self.assertIn("B02", self.source.occupied_blocks())
        self.source.ingest(snapshot(False, True))
        self.assertTrue(self.source.healthy)
        self.assertEqual(self.source.occupied_blocks(), {"B02": ("sensor:computer:1:2",)})
        self.source.ingest(snapshot(False, False))
        self.assertEqual(self.source.occupied_blocks(), {})
        self.now += 4
        self.assertFalse(self.source.healthy)
        self.assertIn("unknown", self.source.occupied_blocks()["B02"][0])
        self.source.ingest(snapshot(False, False))
        self.assertTrue(self.source.healthy)
        with self.assertRaisesRegex(ValueError, "missing mapped"):
            self.source.ingest(snapshot(False))
        self.assertFalse(self.source.healthy)
        self.assertIn("B02", self.source.occupied_blocks())
        self.source.ingest(snapshot(False, False))
        self.source.close()
        self.assertFalse(self.source.healthy)
        self.assertIn("B02", self.source.occupied_blocks())

    def test_strict_frame_validation_does_not_reuse_previous_clear_snapshot(self):
        bad = [b'not JSON', b'\xff', {}, {"contacts": None}, {"contacts": [], "extra": 1},
               {"contacts": [{"module": True, "input": 1, "occupied": False}]},
               {"contacts": [{"module": 0, "input": 1, "occupied": False}]},
               {"contacts": [{"module": 1, "input": 1, "occupied": 0}]},
               {"contacts": [{"module": 1, "input": 1, "occupied": False}] * 2},
               b'x' * 65537]
        for frame in bad:
            with self.subTest(frame=str(frame)[:80]):
                self.source.ingest(snapshot(False, False))
                with self.assertRaises(ValueError):
                    self.source.ingest(frame)
                self.assertFalse(self.source.healthy)
                self.assertIn("B02", self.source.occupied_blocks())

    def test_mapping_changes_require_new_snapshot(self):
        self.source.ingest(snapshot(False, False))
        self.source.replace_mapping({(1, 1): "B03"})
        self.assertFalse(self.source.healthy)
        self.assertIn("B03", self.source.occupied_blocks())
        self.assertNotIn("B02", self.source.occupied_blocks())

    def test_connection_validation(self):
        for config in ({"transport": "udp"}, {"timeout_s": float("nan")}, {"timeout_s": True},
                       {"timeout_s": .1}, {"port": True}, {"port": 0}, {"baudrate": 0},
                       {"host": ""}, {"serial_port": "COM3\n"}, {"extra": 1}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_computer_feedback(config)

    def test_real_tcp_split_frames_receive_only_and_disconnect(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.addCleanup(listener.close)
        self.source.close()
        self.source.config = validate_computer_feedback({"transport": "tcp", "port": listener.getsockname()[1]})
        self.source.connect()
        peer, _ = listener.accept()
        self.addCleanup(peer.close)
        frame = json.dumps(snapshot(False, True)).encode() + b'\n'
        peer.sendall(frame[:20])
        self.assertFalse(self.source.healthy)
        peer.sendall(frame[20:])
        wait_for(lambda: self.source.healthy)
        self.assertIn("B02", self.source.occupied_blocks())
        peer.settimeout(.05)
        with self.assertRaises(socket.timeout):
            peer.recv(1)  # No power, locomotive, poll or handshake commands.
        peer.sendall(json.dumps(snapshot(False, False)).encode() + b'\n')
        wait_for(lambda: self.source.occupied_blocks() == {})
        peer.close()
        wait_for(lambda: not self.source.payload()["connected"])
        self.assertIn("B02", self.source.occupied_blocks())
        self.assertIn("lost", self.source.error)

    def test_serial_receive_and_close_with_fake_device(self):
        class SerialDevice:
            in_waiting = 100
            def __init__(self):
                self.frames = queue.Queue()
                self.closed = False
            def read(self, size):
                if self.closed:
                    raise OSError("closed")
                try:
                    return self.frames.get(timeout=.05)
                except queue.Empty:
                    return b''
            def close(self):
                self.closed = True
        device = SerialDevice()
        factory = unittest.mock.Mock(return_value=device)
        self.source.config["serial_port"] = "COM7"
        with patch.dict("sys.modules", {"serial": types.SimpleNamespace(Serial=factory)}):
            self.source.connect()
        factory.assert_called_once_with("COM7", 115200, timeout=.25, write_timeout=.5)
        device.frames.put(json.dumps(snapshot(False, False)).encode() + b'\r\n')
        wait_for(lambda: self.source.healthy)
        device.frames.put(json.dumps(snapshot(True, False)).encode() + b'\n')
        wait_for(lambda: bool(self.source.occupied_blocks()))
        self.source.close()
        self.assertTrue(device.closed)
        self.assertFalse(self.source.payload()["connected"])

    def test_failed_connect_retains_unknown_protection(self):
        self.source.config["serial_port"] = ""
        with self.assertRaisesRegex(ValueError, "port"):
            self.source.connect()
        self.assertFalse(self.source.payload()["connected"])
        self.assertIn("B02", self.source.occupied_blocks())


class ComputerFeedbackApplicationTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()
        self.app.stop_motion_clock()
        self.addCleanup(self.app.close)

    def assign(self, block="B02", system="computer", contacts=None):
        return self.app.command({"type": "set_block_feedback", "system": system, "block_id": block,
                                 "contacts": [{"module": 1, "input": 1}] if contacts is None else contacts})

    def physical(self, system="ecos"):
        self.app.update_settings({"hardware": {"system": system, "host": "127.0.0.1"}})
        track = FakePhysicalTrack()
        with patch.object(ControllerRuntime, "create_track", return_value=track):
            self.app.command({"type": "connect_hardware"})
        return track

    def test_independent_addresses_and_simulation_preview(self):
        self.assign("B02", "z21")
        before = self.app.runtime.track.get_snapshot()
        self.assign("B03")  # Same numeric contact belongs to another physical source.
        source = self.app._track_trigger_controller.computer
        source._connected = True
        source.ingest(snapshot(True))
        self.assertEqual(self.app.runtime.track.get_snapshot(), before)
        self.assertEqual(source.occupied_blocks(), {"B03": ("sensor:computer:1:1",)})
        payload = self.app._track_trigger_controller.block_feedback_payload("computer")
        self.assertEqual(len(payload["assignments"]), 1)
        self.assertEqual(payload["assignments"][0]["sources"], ["block"])
        with self.assertRaisesRegex(ValueError, "already assigned"):
            self.assign("B04")

    def test_station_union_health_and_direct_movement_guard(self):
        self.assign()
        track = self.physical()
        source = self.app._track_trigger_controller.computer
        track.set_power(True)
        self.assertFalse(track.feedback_healthy)
        self.assertIn("B02", track.get_snapshot().occupied_blocks)
        self.assertFalse(track.set_train_speed_by_address(3, .5).accepted)
        self.assertTrue(track.set_train_speed_by_address(3, 0).accepted)
        source._connected = True
        source.ingest(snapshot(False))
        self.assertTrue(track.feedback_healthy)
        self.assertTrue(track.set_train_speed_by_address(3, .5).accepted)
        from dataclasses import replace
        track._snapshot = replace(track._snapshot, occupied_blocks={"B02": ("sensor:station:3:1",)})
        self.assertEqual(track.get_snapshot().occupied_blocks["B02"], ("sensor:station:3:1",))
        source.ingest(snapshot(True))
        self.assertEqual(set(track.get_snapshot().occupied_blocks["B02"]), {"sensor:station:3:1", "sensor:computer:1:1"})
        self.assertEqual(track._snapshot.occupied_blocks["B02"], ("sensor:station:3:1",), "External overlay is not stored in station state")

    def test_unhealthy_feedback_stops_dispatch_and_does_not_auto_resume(self):
        self.assign()
        track = self.physical()
        track.set_power(True)
        source = self.app._track_trigger_controller.computer
        now = [0]
        source._clock = lambda: now[0]
        source._connected = True
        source.ingest(snapshot(False))
        dispatcher = self.app.runtime.dispatcher
        dispatcher.set_mode("T1", ControlMode.AUTOMATIC)
        now[0] = 4
        self.app.runtime.tick()
        self.assertEqual(dispatcher.trains["T1"].mode, ControlMode.STOPPED)
        source.ingest(snapshot(False))
        self.app.runtime.tick()
        self.assertEqual(dispatcher.trains["T1"].mode, ControlMode.STOPPED)

    def test_power_guard_and_failed_persistence_rollback(self):
        self.assign()
        track = self.physical()
        self.app.command({"type": "track_power", "enabled": True})
        for command in ({"type": "connect_computer_feedback"}, {"type": "disconnect_computer_feedback"},
                        {"type": "set_block_feedback", "system": "computer", "block_id": "B02", "contacts": []}):
            with self.assertRaisesRegex(ValueError, "power off"):
                self.app.command(command)
        self.app.command({"type": "track_power", "enabled": False})
        source = self.app._track_trigger_controller.computer
        with patch.object(self.app, "_persist_operating_plan", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.assign("B03", contacts=[{"module": 2, "input": 1}])
            with self.assertRaises(OSError):
                self.app.command({"type": "configure_computer_feedback", "config": {"host": "changed"}})
        self.assertEqual(source.mapping, {(1, 1): "B02"})
        self.assertEqual(source.config["host"], "127.0.0.1")
        self.assertIs(track.computer_feedback, source)

    def test_station_changes_retain_computer_provider(self):
        self.assign()
        first = self.physical()
        source = self.app._track_trigger_controller.computer
        source._connected = True
        source.ingest(snapshot(True))
        second = self.physical("marklin_cs3")
        self.assertIs(first.computer_feedback, second.computer_feedback)
        self.assertTrue(source.healthy)
        self.assertIn("B02", second.get_snapshot().occupied_blocks)
        with patch.object(ControllerRuntime, "create_track", return_value=SimulatedTrackSystem()):
            self.app.command({"type": "disconnect_hardware"})
        self.assertTrue(source.payload()["connected"])
        self.assertFalse(hasattr(self.app.runtime.track, "computer_feedback"))

    def test_restart_restores_settings_without_opening_detector_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "app.sqlite3")
            app = ControllerApplication.sample(database_path=path)
            try:
                app.command({"type": "configure_computer_feedback", "config": {"transport": "tcp", "host": "192.168.1.50", "port": 5544}})
                app.command({"type": "set_block_feedback", "system": "computer", "block_id": "B02", "contacts": [{"module": 1, "input": 1}]})
            finally:
                app.close()
            with patch.object(ComputerFeedback, "connect", side_effect=AssertionError("implicit activation")):
                restored = ControllerApplication.sample(database_path=path)
            try:
                source = restored._track_trigger_controller.computer
                self.assertEqual(source.config["host"], "192.168.1.50")
                self.assertEqual(source.mapping, {(1, 1): "B02"})
                self.assertFalse(source.payload()["connected"])
            finally:
                restored.close()


if __name__ == "__main__":
    unittest.main()
