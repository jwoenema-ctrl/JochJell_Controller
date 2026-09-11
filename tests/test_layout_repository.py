"""Round-trip coverage for persisted layout snapshots."""

from __future__ import annotations

import unittest

from backend.core.models import (
    Block,
    LayoutSnapshot,
    Platform,
    PhotoScan,
    Point,
    Schedule,
    ScheduleStop,
    Signal,
    Station,
    Train,
    TrainModelInfo,
    Turnout,
    Turntable,
    Waypoint,
)
from backend.infrastructure.layout_repository import SQLiteLayoutRepository


class LayoutRepositoryTests(unittest.TestCase):
    def test_complete_snapshot_round_trip(self) -> None:
        snapshot = LayoutSnapshot(
            revision=4,
            blocks=(
                Block("B1", "West", neighbor_ids=("B2",), position=Point(10, 20)),
                Block("B2", "East", neighbor_ids=("B1",), position=Point(120, 20)),
                Block("B3", "Yard"),
            ),
            turnouts=(Turnout("T1", "Yard entry", "B1", "B2", "B3", address=12),),
            stations=(Station("ST1", "Central", block_ids=("B2",), platform_ids=("P1",), waypoint_ids=("W1",)),),
            signals=(Signal("SG1", "East signal", "B1", "B2", address=20),),
            waypoints=(Waypoint("W1", "Central point", ("B1", "B2"), Point(10, 20)),),
            turntables=(Turntable("TT1", "Yard table", ("B3",), position=Point(30, 40), address=44),),
            platforms=(Platform("P1", "Platform 1", "ST1", "B2", 1800),),
            trains=(Train("TR1", "Test consist", TrainModelInfo("Roco", "1234", "BR 218"), decoder_address=101, length_mm=1200, mass_g=420000),),
            schedules=(Schedule("SC1", "Morning", "TR1", (ScheduleStop("ST1", "P1", 0, 60),)),),
            scans=(PhotoScan("SCAN1", "Yard scan", "Front view", "scans/yard.jpg", Point(0.25, 0.75)),),
        )
        with SQLiteLayoutRepository() as repository:
            record = repository.save("layout-1", snapshot, name="Main layout")
            self.assertEqual(record.name, "Main layout")
            self.assertEqual(repository.list()[0].layout_id, "layout-1")
            self.assertEqual(repository.load("layout-1"), snapshot)
            self.assertTrue(repository.delete("layout-1"))
            self.assertIsNone(repository.load("layout-1"))


if __name__ == "__main__":
    unittest.main()
