"""Focused validation coverage for complete layout snapshots."""

from __future__ import annotations

from dataclasses import fields, replace
import unittest

from backend.core.models import (
    Block,
    LayoutSnapshot,
    Platform,
    Schedule,
    ScheduleStop,
    Signal,
    Station,
    Train,
    Turnout,
    Turntable,
    Waypoint,
)


class LayoutSnapshotValidationTests(unittest.TestCase):
    @staticmethod
    def snapshot_kwargs(snapshot: LayoutSnapshot) -> dict[str, object]:
        return {field.name: getattr(snapshot, field.name) for field in fields(LayoutSnapshot)}

    def make_snapshot(self) -> LayoutSnapshot:
        return LayoutSnapshot(
            blocks=(
                Block("B1", neighbor_ids=("B2",), waypoint_ids=("W1",), platform_ids=("P1",)),
                Block("B2"),
                Block("B3"),
            ),
            turnouts=(Turnout("T1", "Yard turnout", "B1", "B2", "B3"),),
            stations=(Station("ST1", "Central", ("B1",), ("P1",), ("W1",)),),
            signals=(Signal("SG1", "Exit", "B1", "B2"),),
            waypoints=(Waypoint("W1", connected_node_ids=("B1", "B2", "TT1")),),
            turntables=(Turntable("TT1", connected_block_ids=("B2",), aligned_block_id="B2", occupied_by="TR1"),),
            platforms=(Platform("P1", "Platform 1", "ST1", "B1"),),
            trains=(Train("TR1", "Test train", current_block_id="B1", destination_block_id="B2"),),
            schedules=(Schedule("SC1", "Morning", "TR1", (ScheduleStop("ST1", "P1", 0, 60),)),),
        )

    def test_valid_cross_references_are_accepted(self) -> None:
        snapshot = self.make_snapshot()

        self.assertEqual(snapshot.block("B1").platform_ids, ("P1",))
        self.assertEqual(snapshot.schedules[0].stops[0].platform_id, "P1")

    def test_empty_snapshot_and_optional_references_remain_valid(self) -> None:
        self.assertEqual(LayoutSnapshot.empty(), LayoutSnapshot())
        self.assertEqual(LayoutSnapshot(blocks=(Block("B1"),), trains=(Train("TR1", "Train"),)).trains[0].current_block_id, None)

    def test_block_references_must_exist(self) -> None:
        for field in ("neighbor_ids", "waypoint_ids", "platform_ids"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    LayoutSnapshot(blocks=(replace(Block("B1"), **{field: ("missing",)}),))

    def test_layout_entities_reference_existing_entities(self) -> None:
        cases = (
            ("turnout", lambda snapshot: replace(snapshot, turnouts=(replace(snapshot.turnouts[0], entry_block_id="missing"),))),
            ("station", lambda snapshot: replace(snapshot, stations=(replace(snapshot.stations[0], block_ids=("missing",)),))),
            ("signal", lambda snapshot: replace(snapshot, signals=(replace(snapshot.signals[0], protects_block_id="missing"),))),
            ("waypoint", lambda snapshot: replace(snapshot, waypoints=(replace(snapshot.waypoints[0], connected_node_ids=("missing",)),))),
            ("turntable", lambda snapshot: replace(snapshot, turntables=(replace(snapshot.turntables[0], connected_block_ids=("missing",), aligned_block_id=None),))),
            ("platform", lambda snapshot: replace(snapshot, platforms=(replace(snapshot.platforms[0], station_id="missing"),))),
            ("train", lambda snapshot: replace(snapshot, trains=(replace(snapshot.trains[0], current_block_id="missing"),))),
        )
        for entity, make_invalid in cases:
            with self.subTest(entity=entity):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    make_invalid(self.make_snapshot())

    def test_schedule_and_stop_references_must_exist(self) -> None:
        snapshot = self.make_snapshot()
        with self.assertRaisesRegex(ValueError, "unknown train ID"):
            LayoutSnapshot(**self.snapshot_kwargs(replace(snapshot, schedules=(replace(snapshot.schedules[0], train_id="missing"),))))
        with self.assertRaisesRegex(ValueError, "unknown station ID"):
            LayoutSnapshot(**self.snapshot_kwargs(replace(snapshot, schedules=(replace(snapshot.schedules[0], stops=(ScheduleStop("missing"),)),))))
        with self.assertRaisesRegex(ValueError, "unknown platform ID"):
            LayoutSnapshot(**self.snapshot_kwargs(replace(snapshot, schedules=(replace(snapshot.schedules[0], stops=(ScheduleStop("ST1", "missing"),)),))))

    def test_platform_must_belong_to_its_station_and_block(self) -> None:
        snapshot = self.make_snapshot()
        invalid_station = self.snapshot_kwargs(snapshot)
        invalid_station["stations"] = (snapshot.stations[0], Station("ST2", "Other", ("B1",), ()))
        invalid_station["platforms"] = (Platform("P1", "Platform 1", "ST2", "B1"),)
        with self.assertRaisesRegex(ValueError, "must belong to (the|its) station"):
            LayoutSnapshot(**invalid_station)

        invalid_block = self.snapshot_kwargs(snapshot)
        invalid_block["blocks"] = (replace(snapshot.blocks[0], platform_ids=("P1",)), snapshot.blocks[1], snapshot.blocks[2])
        invalid_block["stations"] = (Station("ST1", "Central", ("B1", "B2"), ("P1",), ("W1",)),)
        invalid_block["platforms"] = (Platform("P1", "Platform 1", "ST1", "B2"),)
        with self.assertRaisesRegex(ValueError, "must belong to the block"):
            LayoutSnapshot(**invalid_block)

if __name__ == "__main__":
    unittest.main()
