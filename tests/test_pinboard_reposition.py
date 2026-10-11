"""Manual placement is independent from calibrated driving and detector state."""
from copy import deepcopy
from unittest.mock import patch, PropertyMock
from types import SimpleNamespace
import unittest

from backend.api.server import ControllerApplication
from backend.runtime import ControllerRuntime
from tests.test_hardware_switching import FakePhysicalTrack


class PinboardRepositionTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()
        self.app.stop_motion_clock()
        self.addCleanup(self.app.close)

    def place(self, **updates):
        return self.app.command({"type": "reposition_train_on_track", "train_id": "t2", "x": 560, "y": 178, **updates})

    def physical(self):
        self.app.update_settings({"hardware": {"system": "ecos", "host": "127.0.0.1"}})
        track = FakePhysicalTrack()
        with patch.object(ControllerRuntime, "create_track", return_value=track):
            self.app.command({"type": "connect_hardware"})
        track.commands.clear()
        return track

    def test_simulation_places_immediately_without_calibration_or_drive(self):
        with patch.object(self.app.runtime.calibration, "history", return_value=()) as history, \
             patch.object(self.app.runtime.track, "set_train_speed", side_effect=AssertionError("drive")):
            state = self.place()
        train = next(t for t in state["trains"] if t["id"] == "t2")
        self.assertEqual(train["motion"]["from_block_id"], "b02")
        self.assertAlmostEqual(train["motion"]["position"], (560 - 453) / 250)
        self.assertEqual(train["motion"]["speed"], 0)
        self.assertIsNone(train["target_coordinate"])
        self.assertTrue(all(not call.args and not call.kwargs for call in history.call_args_list), "Only the dashboard history is read, no train calibration is requested")

    def test_simulation_drop_uses_turnout_curves_visible_on_the_canvas(self):
        state = self.place(x=390, y=290)
        train = next(t for t in state["trains"] if t["id"] == "t2")
        self.assertEqual((train["motion"]["from_block_id"], train["motion"]["to_block_id"]), ("b02", "b04"))

    def test_unpowered_unaddressed_wagon_can_be_repositioned(self):
        self.app.command({"type": "add_train", "train": {"id": "wagon", "name": "Wagon", "address": None,
            "mode": "stopped", "speed": 0, "block_id": "B04", "length_mm": 160,
            "consist": [{"id": "wagon-body", "type": "freight_wagon", "name": "Wagon", "length_mm": 160}]}})
        self.app.command({"type": "track_power", "enabled": False})
        state = self.place(train_id="wagon")
        train = next(t for t in state["trains"] if t["id"] == "wagon")
        self.assertEqual(train["position"], "B02")
        self.assertEqual(train["motion"]["speed"], 0)

    def test_invalid_coordinates_and_unknown_trains_do_not_change_position(self):
        before = deepcopy(self.app.trains)
        motion = self.app.runtime.track.get_snapshot()
        for updates in ({"train_id": "missing"}, {"x": None}, {"x": float("nan")}, {"x": float("inf")}, {"x": 5000, "y": 5000}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.place(**updates)
            self.assertEqual(self.app.trains, before)
            self.assertEqual(self.app.runtime.track.get_snapshot(), motion)

    def test_simulation_rejects_another_trains_block(self):
        before = self.app.runtime.track.get_snapshot()
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.place(x=300, y=178)
        self.assertEqual(self.app.runtime.track.get_snapshot(), before)

    def test_moving_train_is_rejected_without_issuing_a_stop_or_drive(self):
        before = self.app.runtime.track.get_snapshot()
        with patch.object(self.app.runtime.track, "stop_train", side_effect=AssertionError("stop")), \
             patch.object(self.app.runtime.track, "set_train_speed", side_effect=AssertionError("drive")), \
             self.assertRaisesRegex(ValueError, "stop the train"):
            self.place(train_id="t1")
        self.assertEqual(self.app.runtime.track.get_snapshot(), before)

    def test_active_execution_and_routines_are_rejected_before_mutation(self):
        before = deepcopy(self.app.trains)
        with patch.object(type(self.app.runtime.coordinate_movement), "status", new_callable=PropertyMock,
                          return_value=SimpleNamespace(train_id="train-3", state="running")), \
             self.assertRaisesRegex(ValueError, "active routine"):
            self.place()
        self.assertEqual(self.app.trains, before)
        self.app._playback_runs["train-3"] = {}
        try:
            with self.assertRaisesRegex(ValueError, "active routine"):
                self.place()
        finally:
            self.app._playback_runs.clear()
        self.assertEqual(self.app.trains, before)

    def test_hardware_manual_position_never_changes_detector_or_drive_state(self):
        track = self.physical()
        before = track.get_snapshot()
        with patch.object(track, "report_train_position", side_effect=AssertionError("position report")), \
             patch.object(track, "set_train_speed", side_effect=AssertionError("drive")), \
             patch.object(track, "set_power", side_effect=AssertionError("power")), \
             patch.object(self.app.runtime.calibration, "history", return_value=()) as history:
            state = self.place()
        train = next(t for t in state["trains"] if t["id"] == "t2")
        self.assertEqual(train["pinboard_position"]["source"], "manual")
        self.assertEqual(train["pinboard_position"]["x"], 560)
        self.assertEqual(train["position"], "—", "Manual graphics do not identify a physical train")
        self.assertEqual(track.get_snapshot(), before)
        self.assertEqual(track.commands, [])
        self.assertFalse(state["track_power"])
        self.assertTrue(all(not call.args and not call.kwargs for call in history.call_args_list))

    def test_hardware_manual_position_survives_polling_and_clear_report_supersedes_it(self):
        track = self.physical()
        track.report_train_position("train-3", "B03", ("B03", "B04"))
        self.place()
        for _ in range(3):
            train = next(t for t in self.app.state()["trains"] if t["id"] == "t2")
            self.assertEqual(train["pinboard_position"]["x"], 560)
        track.report_train_position("train-3", "B04", ("B03", "B04"))
        train = next(t for t in self.app.state()["trains"] if t["id"] == "t2")
        self.assertIsNone(train["pinboard_position"])
        self.assertEqual(track.commands, [])

    def test_manual_placement_removes_old_drive_destination(self):
        self.physical()
        raw = next(t for t in self.app.trains if t["id"] == "train-3")
        raw["target_coordinate"] = {"x": 703, "y": 178}
        self.place()
        self.assertIsNone(raw["target_coordinate"])
        with self.assertRaisesRegex(ValueError, "create a coordinate target"):
            self.app.command({"type": "execute_coordinate_move", "train_id": "t2", "confirm": True})

    def test_normal_locomotive_drive_still_requires_calibration(self):
        with self.assertRaisesRegex(ValueError, "calibration measurement"):
            self.app.command({"type": "move_train_to_coordinate", "train_id": "t2", "x": 560, "y": 178})
        self.place()


if __name__ == "__main__":
    unittest.main()
