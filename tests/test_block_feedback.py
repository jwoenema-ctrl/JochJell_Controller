"""Durable physical block assignments and their occupancy safety boundaries."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.api.server import ControllerApplication
from backend.infrastructure.interfaces import CommandResult
from backend.infrastructure.operating_plan import OperatingPlanRepository
from backend.runtime import ControllerRuntime
from tests.test_hardware_switching import FakePhysicalTrack


class BlockFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()
        self.app.stop_motion_clock()
        self.addCleanup(self.app.close)

    def assign(self, block="B02", contacts=None, system="z21", app=None):
        return (app or self.app).command({"type": "set_block_feedback", "system": system, "block_id": block,
                                         "contacts": [{"module": 1, "input": 1}] if contacts is None else contacts})

    def trigger(self, block="B02", module=1, contact=1):
        return {"id": "shared-trigger", "block_id": block, "detector": {"module": module, "input": contact},
                "actions": [{"type": "function", "function_number": 0, "mode": "on"}]}

    def test_assignments_are_profile_specific_and_do_not_move_or_power_trains(self):
        before = self.app.runtime.track.get_snapshot()
        with ExitStack() as stack:
            for method in ("tick", "set_power", "set_train_speed", "stop_train", "set_train_route"):
                stack.enter_context(patch.object(self.app.runtime.track, method, side_effect=AssertionError(method)))
            self.assign("b02")
            self.assign("B03", system="ecos")
        self.assertEqual(self.app.runtime.track.get_snapshot(), before)
        controller = self.app._track_trigger_controller
        self.assertEqual(controller.feedback_for_profile("z21"), {(1, 1): "B02"})
        self.assertEqual(controller.feedback_for_profile("ecos"), {(1, 1): "B03"})
        self.assertEqual(controller.feedback_for_profile("marklin_cs3"), {})
        self.assertEqual(controller.block_feedback_payload("ecos")["assignments"][0]["sources"], ["block"])

    def test_validation_and_conflicts_leave_existing_assignments_intact(self):
        self.assign()
        before = self.app._track_trigger_controller.payload()
        invalid = [
            {"contacts": None}, {"contacts": {}}, {"system": "simulation"}, {"system": "unknown"},
            {"block_id": "MISSING", "contacts": [{"module": 2, "input": 1}]}, {"contacts": [{"module": True, "input": 1}]},
            {"contacts": [{"module": 1, "input": 0}]}, {"contacts": [{"module": 0, "input": 1}]},
            {"contacts": [{"module": 1, "input": 9}]}, {"contacts": [{"module": 256, "input": 1}]},
            {"contacts": [{"module": 1, "input": 1, "extra": 1}]},
            {"contacts": [{"module": 1, "input": 2}, {"module": 1, "input": 2}]},
            {"block_id": "B03", "contacts": [{"module": 2, "input": 1}, {"module": 1, "input": 1}]},
        ]
        for update in invalid:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.app.command({"type": "set_block_feedback", "system": "z21", "block_id": "B02", "contacts": [], **update})
            self.assertEqual(self.app._track_trigger_controller.payload(), before)

    def test_assignments_survive_restart_and_old_plans_remain_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "controller.sqlite3")
            app = ControllerApplication.sample(database_path=path)
            self.assign(contacts=[{"module": 2, "input": 1}, {"module": 2, "input": 8}], app=app)
            app.close()
            restored = ControllerApplication.sample(database_path=path)
            try:
                self.assertEqual(restored.feedback_map, {(2, 1): "B02", (2, 8): "B02"})
                self.assertEqual(len(restored._track_trigger_controller.block_feedback), 2)
            finally:
                restored.close()
            legacy = Path(directory) / "legacy.json"
            legacy.write_text('{"version": 2, "schedules": [], "routines": [], "track_triggers": []}', encoding="utf-8")
            self.assertEqual(OperatingPlanRepository(legacy).load()["block_feedback"], [])

    def test_removing_trigger_keeps_independent_mapping_and_conflicts_are_rejected(self):
        self.assign()
        self.app.command({"type": "save_track_trigger", "trigger": self.trigger()})
        self.assertEqual(self.app._track_trigger_controller.block_feedback_payload("z21")["assignments"][0]["sources"], ["block", "trigger"])
        with self.assertRaises(ValueError):
            self.assign("B03")
        with self.assertRaises(ValueError):
            self.app.command({"type": "save_track_trigger", "trigger": self.trigger("B03")})
        self.app.command({"type": "delete_track_trigger", "trigger_id": "shared-trigger"})
        self.assertEqual(self.app.feedback_map, {(1, 1): "B02"})
        self.assign(contacts=[])
        self.assertEqual(self.app.feedback_map, {})

    def test_removing_independent_assignment_does_not_remove_trigger_mapping(self):
        self.assign()
        self.app.command({"type": "save_track_trigger", "trigger": self.trigger()})
        self.assign(contacts=[])
        self.assertEqual(self.app.feedback_map, {(1, 1): "B02"})
        self.assertEqual(self.app._track_trigger_controller.block_feedback, [])

    def test_environment_mapping_is_visible_and_cannot_be_stolen(self):
        app = ControllerApplication.sample(feedback_map={(3, 1): "B02"})
        self.addCleanup(app.close)
        with self.assertRaises(ValueError):
            self.assign("B03", [{"module": 3, "input": 1}], app=app)
        self.assertEqual(app._track_trigger_controller.block_feedback_payload("z21")["assignments"][0]["sources"], ["environment"])

    def test_profile_address_limits_accept_adapter_boundaries(self):
        cases = [("z21", 255, 8), ("z21_white", 1, 8), ("z21_start", 1, 8), ("dr5000", 255, 8),
                 ("ecos", 256, 16), ("xpressnet", 0, 8), ("marklin_cs2", 65535, 65535), ("marklin_cs3", 0, 1)]
        for system, module, contact in cases:
            with self.subTest(system=system):
                self.assign(contacts=[{"module": module, "input": contact}], system=system)
                self.assertEqual(self.app._track_trigger_controller.feedback_for_profile(system), {(module, contact): "B02"})
                with self.assertRaises(ValueError):
                    self.assign(contacts=[{"module": module, "input": contact + 65535}], system=system)

    def test_missing_blocks_keep_inactive_assignments_until_removed(self):
        self.assign()
        self.app.blocks = [block for block in self.app.blocks if str(block["id"]).upper() != "B02"]
        controller = self.app._track_trigger_controller
        self.assertEqual(controller.feedback_for_profile("z21"), {})
        self.assertEqual(controller.block_feedback_payload("z21")["assignments"][0]["available"], False)
        controller.set_block_feedback("z21", "B02", [])
        self.assertEqual(controller.block_feedback, [])

    def test_mapped_blocks_cannot_be_deleted_until_assignments_are_removed(self):
        self.app.command({"type": "add_block", "block": {"id": "EMPTY", "name": "Unused section"}})
        self.assign("EMPTY")
        with self.assertRaisesRegex(ValueError, "hardware detector assignments"):
            self.app.command({"type": "delete_block", "block_id": "EMPTY"})
        self.assign("EMPTY", contacts=[])
        self.app.command({"type": "delete_block", "block_id": "EMPTY"})
        self.assertFalse(any(block["id"] == "EMPTY" for block in self.app.blocks))

    def test_failed_persistence_rolls_back_mapping_and_storage_draft(self):
        self.assign()
        with patch.object(self.app._operating_plan_repository, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.assign(contacts=[{"module": 2, "input": 1}])
        self.assertEqual(self.app.feedback_map, {(1, 1): "B02"})
        self.assertEqual(self.app._track_trigger_controller.block_feedback[0]["module"], 1)

    def test_block_rename_preserves_assignments(self):
        self.assign()
        self.app.command({"type": "track_power", "enabled": False})
        self.app.command({"type": "update_block", "block_id": "B02", "block": {"id": "YARD"}})
        self.assertEqual(self.app.feedback_map, {(1, 1): "YARD"})
        self.assertEqual(self.app._track_trigger_controller.block_feedback[0]["block_id"], "YARD")

    def test_real_adapter_receives_mappings_and_aggregates_multiple_contacts(self):
        self.app.update_settings({"hardware": {"system": "ecos", "host": "127.0.0.1"}})
        self.assign(contacts=[{"module": 1, "input": 1}, {"module": 1, "input": 2}], system="ecos")
        physical = FakePhysicalTrack()
        with patch.object(ControllerRuntime, "create_track", return_value=physical):
            self.app.command({"type": "connect_hardware"})
        physical.commands.clear()
        self.assertEqual(physical.feedback_map, {(1, 1): "B02", (1, 2): "B02"})
        with patch.object(physical, "_read_feedback", return_value=(CommandResult(True, "poll_feedback"), {1: False, 2: True})):
            physical.poll_feedback()
        self.assertIn("B02", physical.get_snapshot().occupied_blocks)
        with patch.object(physical, "_read_feedback", return_value=(CommandResult(True, "poll_feedback"), {1: False, 2: False})):
            physical.poll_feedback()
        self.assertNotIn("B02", physical.get_snapshot().occupied_blocks)
        self.app.command({"type": "track_power", "enabled": True})
        physical.commands.clear()
        with self.assertRaisesRegex(ValueError, "track power off"):
            self.assign(contacts=[{"module": 2, "input": 1}], system="ecos")
        self.assertEqual(physical.feedback_map, {(1, 1): "B02", (1, 2): "B02"})
        self.assertEqual(physical.commands, [])
        self.assign("B03", system="z21")
        self.assertEqual(physical.commands, [], "An inactive profile does not send hardware commands")
        self.app.command({"type": "track_power", "enabled": False})
        physical.commands.clear()
        self.assign(contacts=[], system="ecos")
        self.assertEqual(physical.feedback_map, {})
        self.assertEqual(physical.commands, [])
