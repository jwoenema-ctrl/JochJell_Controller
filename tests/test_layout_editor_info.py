import struct
import unittest
from unittest.mock import Mock

from backend.api.server import ControllerApplication
from backend.infrastructure.interfaces import CommandResult
from backend.infrastructure.real_track import Z21TrackSystem
from backend.infrastructure.z21 import Z21Dataset
from backend.infrastructure.z21_telemetry import decode_system_state


class LayoutEditorTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()

    def tearDown(self):
        self.app.close()

    def test_generated_ids_follow_layout_and_ignore_case(self):
        self.app.command({"type": "add_block", "block": {}})
        self.assertEqual(self.app.blocks[-1]["id"], "B05")
        self.app.command({"type": "add_block", "block": {"id": "b20"}})
        self.app.command({"type": "add_block", "block": {}})
        self.assertEqual(self.app.blocks[-1]["id"], "B21")
        with self.assertRaises(ValueError):
            self.app.command({"type": "add_block", "block": {"id": "b01"}})

    def test_unreferenced_block_can_be_removed_and_runtime_graph_stays_valid(self):
        self.app.command({"type": "add_block", "block": {"id": "b05", "name": "Temporary"}})
        result = self.app.command({"type": "delete_block", "block_id": "b05"})
        self.assertNotIn("B05", [block["id"] for block in self.app.blocks])
        self.assertNotIn("b05", [block["id"] for block in result["layout"]["blocks"]])
        self.assertIsNone(self.app.runtime.layout.graph().node("B05"))
        self.assertEqual(result["events"][-1]["type"], "block_removed")

    def test_referenced_block_cannot_be_removed(self):
        before = [block.copy() for block in self.app.blocks]
        with self.assertRaisesRegex(ValueError, "references it"):
            self.app.command({"type": "remove_block", "block_id": "b04"})
        self.assertEqual(self.app.blocks, before)

    def test_rename_requires_power_off_and_updates_references(self):
        command = {"type": "update_block", "block_id": "b02", "block": {"id": "central"}}
        with self.assertRaisesRegex(ValueError, "power off"):
            self.app.command(command)
        self.app.command({"type": "track_power", "enabled": False})
        self.app.command(command)
        self.assertIn("CENTRAL", [b["id"] for b in self.app.blocks])
        snapshot = self.app._domain_snapshot()
        self.assertNotIn("B02", str(snapshot))
        self.app.save_layout("renamed")
        self.app.load_layout("renamed")
        self.assertIn("CENTRAL", [b["id"] for b in self.app.blocks])

    def test_occupied_block_rename_preserves_direction_and_position(self):
        self.app.command({"type": "set_direction", "train_id": "train-3", "direction": "reverse"})
        self.app.command({"type": "track_power", "enabled": False})
        before = next(t for t in self.app.runtime.track.get_snapshot().trains if t.train_id == "train-3")
        self.app.command({"type": "update_block", "block_id": "B03", "block": {"id": "YARD"}})
        after = next(t for t in self.app.runtime.track.get_snapshot().trains if t.train_id == "train-3")
        self.assertEqual(after.block_id, "YARD")
        self.assertEqual((before.position, before.direction), (after.position, after.direction))

    def test_invalid_and_duplicate_rename_do_not_mutate(self):
        self.app.command({"type": "track_power", "enabled": False})
        before = self.app._domain_snapshot()
        for name in ("b01", "bad id", "", "1bad"):
            with self.assertRaises(ValueError):
                self.app.command({"type": "update_block", "block_id": "B02", "block": {"id": name}})
            self.assertEqual(before, self.app._domain_snapshot())

    def test_info_counts_and_no_fake_simulation_power(self):
        info = self.app.layout_info()
        self.assertEqual(info["block_count"], 4)
        self.assertEqual(info["train_count"], 2)
        self.assertEqual(info["manual_trains"], 1)
        self.assertEqual(info["automatic_trains"], 1)
        self.assertEqual(info["occupied_blocks"], 2)
        self.assertEqual(info["active_routes"], 1)
        self.assertFalse(info["power"]["available"])
        self.app.command({"type": "track_power", "enabled": False})
        self.assertEqual(self.app.layout_info()["active_routes"], 0)


class TelemetryTests(unittest.TestCase):
    def test_system_state_and_read_only_request(self):
        payload = struct.pack("<hhhhHHBBBB", 500, 0, 400, 35, 19000, 18000, 0, 0, 0, 0)
        decoded = decode_system_state(payload)
        self.assertEqual(decoded["current_a"], .5)
        self.assertEqual(decoded["estimated_watts"], 7.2)
        self.assertTrue(decoded["track_power"])
        transport = Mock()
        transport.request_datasets.return_value = (CommandResult(True, "system_state", ""), (Z21Dataset(0x84, payload),))
        track = Z21TrackSystem(transport)
        self.assertEqual(track.read_power_telemetry(), decoded)
        self.assertEqual(transport.request_datasets.call_args.args[0], bytes.fromhex("04008500"))
        transport.send_dataset.assert_not_called()
        transport.request_datasets.return_value = (CommandResult(False, "system_state", "offline"), ())
        self.assertFalse(track.read_power_telemetry()["available"])

    def test_invalid_payload_and_power_flags(self):
        with self.assertRaises(ValueError):
            decode_system_state(b"short")
        data = struct.pack("<hhhhHHBBBB", 0, 0, 0, 20, 19000, 18000, 6, 0, 0, 0)
        self.assertFalse(decode_system_state(data)["track_power"])
        self.assertTrue(decode_system_state(data)["short_circuit"])
