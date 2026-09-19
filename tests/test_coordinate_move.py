from dataclasses import dataclass
import math
import unittest

from backend.services.coordinate_move import (
    CoordinateMovementPlanner,
    MovementPlanValidationError,
)


BLOCKS = [
    {"id": "A", "x": 0, "y": 0, "width": 20, "height": 20},
    {"id": "B", "x": 100, "y": 0, "width": 20, "height": 20},
]
EDGES = [{"from": "A", "to": "B", "length_mm": 1000}]
CALIBRATION = [{"speed_kmh": 10, "duration_ms": 100, "measured_distance_mm": 50}]


class CoordinateMovementTests(unittest.TestCase):
    def planner(self, **kwargs):
        return CoordinateMovementPlanner(BLOCKS, EDGES, CALIBRATION, **kwargs)

    def test_coordinate_becomes_forward_plan_with_remaining_distance_and_duration(self):
        plan = self.planner().plan("train-7", 60, 10)
        self.assertEqual(plan.source_block_id, "A")
        self.assertEqual(plan.target_block_id, "B")
        self.assertAlmostEqual(plan.progress, 0.5)
        self.assertAlmostEqual(plan.distance_mm, 500)
        self.assertEqual(plan.estimated_duration_ms, 1000)
        self.assertEqual(plan.speed_kmh, 10)

    def test_reverse_direction_swaps_blocks_and_uses_progress_as_remaining_distance(self):
        plan = self.planner().plan("train-7", 60, 10, direction="reverse")
        self.assertEqual((plan.source_block_id, plan.target_block_id), ("B", "A"))
        self.assertAlmostEqual(plan.distance_mm, 500)

    def test_object_style_topology_and_calibration_are_supported(self):
        @dataclass
        class Block:
            id: str
            position: object

        @dataclass
        class Position:
            x: float
            y: float

        @dataclass
        class Edge:
            from_block_id: str
            to_block_id: str
            length_mm: float

        @dataclass
        class Calibration:
            speed_kmh: float
            duration_ms: int
            measured_distance_mm: float

        object_planner = CoordinateMovementPlanner(
            [Block("A", Position(0, 0)), Block("B", Position(100, 0))],
            [Edge("A", "B", 800)],
            Calibration(8, 200, 80),
        )
        plan = object_planner.plan("T1", 25, 0, speed_kmh=8)
        self.assertEqual(plan.target_block_id, "B")
        self.assertAlmostEqual(plan.distance_mm, 600)
        self.assertEqual(plan.estimated_duration_ms, 1500)

    def test_nearest_calibration_is_selected_and_can_be_speed_limited(self):
        movement_planner = CoordinateMovementPlanner(
            BLOCKS,
            EDGES,
            [
                {"speed_kmh": 8, "duration_ms": 100, "measured_distance_mm": 40},
                {"speed_kmh": 12, "duration_ms": 100, "measured_distance_mm": 60},
            ],
            max_speed_delta_kmh=1,
        )
        plan = movement_planner.plan("T1", 10, 0, speed_kmh=11)
        self.assertEqual(plan.calibration_speed_kmh, 12)
        self.assertEqual(plan.estimated_duration_ms, 1667)
        with self.assertRaisesRegex(MovementPlanValidationError, "no calibration"):
            movement_planner.plan("T1", 10, 0, speed_kmh=20)

    def test_invalid_coordinates_are_rejected(self):
        cases = [
            (("T1", float("nan"), 0), "x must be a finite number"),
            (("T1", 20, 0), "coordinate is not on"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                with self.assertRaisesRegex(MovementPlanValidationError, message):
                    self.planner(coordinate_tolerance=5).plan(*args)

    def test_invalid_direction_and_occupied_target_are_rejected(self):
        with self.assertRaisesRegex(MovementPlanValidationError, "direction"):
            self.planner().plan("T1", 40, 0, direction="sideways")
        with self.assertRaisesRegex(MovementPlanValidationError, "occupied"):
            self.planner().plan("T1", 40, 0, occupied_blocks={"B": "T2"})

    def test_missing_or_invalid_calibration_is_rejected_before_planning(self):
        with self.assertRaisesRegex(MovementPlanValidationError, "calibration record"):
            CoordinateMovementPlanner(BLOCKS, EDGES, []).plan("T1", 40, 0)
        with self.assertRaisesRegex(MovementPlanValidationError, "positive"):
            CoordinateMovementPlanner(
                BLOCKS,
                EDGES,
                [{"speed_kmh": 10, "duration_ms": 0, "measured_distance_mm": 50}],
            ).plan("T1", 40, 0)


if __name__ == "__main__":
    unittest.main()
