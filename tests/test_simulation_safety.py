"""Focused safety coverage for the deterministic track simulator."""

from __future__ import annotations

import unittest

from backend.infrastructure.simulation import SimulatedTrackSystem


class SimulationSafetyTests(unittest.TestCase):
    def test_automatic_train_brakes_and_resumes_after_occupied_block_clears(self) -> None:
        track = SimulatedTrackSystem(tick_seconds=0.1, acceleration=1.0)
        track.add_train("occupying", "B02", speed=0.0)
        track.add_train("automatic", "B01", route=("B01", "B02"), speed=1.0)

        speeds = []
        for _ in range(40):
            snapshot = track.tick()
            speeds.append(next(train for train in snapshot.trains if train.train_id == "automatic").speed)

        held = next(train for train in track.get_snapshot().trains if train.train_id == "automatic")
        self.assertTrue(any(0.0 < speed < 1.0 for speed in speeds))
        self.assertEqual(held.speed, 0.0)
        self.assertLess(held.position, 1.0)
        self.assertEqual(held.block_id, "B01")

        track.remove_train("occupying")
        resumed = track.tick()
        automatic = next(train for train in resumed.trains if train.train_id == "automatic")
        self.assertGreater(automatic.speed, 0.0)
        self.assertEqual(automatic.block_id, "B02")

    def test_automatic_train_brakes_at_blocked_authority_and_resumes_when_restored(self) -> None:
        track = SimulatedTrackSystem(tick_seconds=0.1, acceleration=1.0)
        track.add_train("automatic", "B01", route=("B01", "B02", "B03"), speed=1.0)
        track.set_authority("automatic", ("B01", "B02"))

        for _ in range(40):
            track.tick()

        held = next(train for train in track.get_snapshot().trains if train.train_id == "automatic")
        self.assertEqual(held.block_id, "B02")
        self.assertEqual(held.speed, 0.0)
        self.assertLess(held.position, 1.0)

        track.set_authority("automatic", ("B01", "B02", "B03"))
        for _ in range(20):
            track.tick()
        resumed = next(train for train in track.get_snapshot().trains if train.train_id == "automatic")
        self.assertEqual(resumed.block_id, "B03")
        self.assertGreater(resumed.position, 0.0)

    def test_restrictive_signal_is_a_safe_boundary_until_cleared(self) -> None:
        track = SimulatedTrackSystem(tick_seconds=0.1, acceleration=1.0)
        track.add_train("automatic", "B01", route=("B01", "B02"), speed=1.0)
        track.add_signal("S02", "B02", aspect="red")

        for _ in range(40):
            track.tick()

        held = next(train for train in track.get_snapshot().trains if train.train_id == "automatic")
        self.assertEqual(held.speed, 0.0)
        self.assertEqual(held.block_id, "B01")
        self.assertLess(held.position, 1.0)

        track.set_signal("S02", "green")
        resumed = track.tick()
        self.assertEqual(next(train for train in resumed.trains if train.train_id == "automatic").block_id, "B02")


if __name__ == "__main__":
    unittest.main()
