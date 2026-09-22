"""Tests for per-train manual/automatic/stopped arbitration at the API boundary."""

from __future__ import annotations

import unittest

from backend.api.server import ControllerApplication


class TrainModeApiTests(unittest.TestCase):
    def test_per_train_mode_switch_does_not_change_other_trains(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "set_train_mode", "train_id": "t1", "mode": "automatic"})
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-101")["mode"], "automatic")
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-3")["mode"], "manual")
            self.assertTrue(any(event["type"] == "train_mode_changed" and event["train_id"] == "train-101" for event in app.state()["events"]))

            app.command({"type": "set_train_mode", "train_id": "t2", "mode": "automatic"})
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-101")["mode"], "automatic")
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-3")["mode"], "automatic")
            app.command({"type": "set_train_mode", "train_id": "t1", "mode": "manual"})
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-101")["mode"], "manual")
            self.assertEqual(next(item for item in app.trains if item["id"] == "train-3")["mode"], "automatic")

            stopped = app.command({"type": "switch_train_mode", "train_id": "train-101", "mode": "safe"})
            changed = next(item for item in stopped["trains"] if item["id"] == "t1")
            self.assertEqual(changed["class"], "Stopped")
            self.assertEqual(changed["speed"], 0)
            self.assertEqual(app.runtime.dispatcher.trains["train-101"].mode.value, "stopped")
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
