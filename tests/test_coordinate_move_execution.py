from dataclasses import replace
from types import SimpleNamespace
import unittest

from backend.services.coordinate_move import (
    CoordinateMovementExecutionPlanner,
    CoordinateMovementExecutor,
    CoordinateMovementPlanner,
    MovementExecutionError,
    MovementPlanValidationError,
    build_timed_movement_request,
)
from backend.services.coordinate_execution import (
    CoordinateExecutionError,
    CoordinateMovementExecutor as RuntimeCoordinateMovementExecutor,
)


BLOCKS = [
    {"id": "A", "x": 0, "y": 0, "width": 20, "height": 20},
    {"id": "B", "x": 100, "y": 0, "width": 20, "height": 20},
]
EDGES = [{"from": "A", "to": "B", "length_mm": 1000}]
CALIBRATION = {"speed_kmh": 10, "duration_ms": 100, "measured_distance_mm": 50}


class FakeTimer:
    def __init__(self, seconds, callback):
        self.seconds = seconds
        self.callback = callback
        self.started = False
        self.cancelled = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback()


class FakeDispatcher:
    def __init__(self, *, mode="manual", desired_speed=0.0):
        self.control = SimpleNamespace(mode=mode, desired_speed=desired_speed, manual_speed=0.0, automatic_speed=0.0)
        self.speed_commands = []

    def register_train(self, train_id):
        self.control.train_id = train_id
        return self.control

    def manual_speed(self, train_id, speed):
        self.speed_commands.append((train_id, speed))
        self.control.manual_speed = speed
        return SimpleNamespace(accepted=True, detail="")


class FakeTrack:
    def __init__(self, *, direction=True, speed=0.0, target_speed=0.0):
        self.direction = direction
        self.motion = SimpleNamespace(train_id="train-7", speed=speed, target_speed=target_speed)
        self.direction_commands = []
        self.stop_commands = []

    def get_snapshot(self):
        return SimpleNamespace(trains=(self.motion,))

    def get_train_direction(self, train_id):
        return self.direction

    def set_train_direction(self, train_id, *, forward):
        self.direction_commands.append((train_id, forward))
        self.direction = forward
        return SimpleNamespace(accepted=True, detail="")

    def stop_train(self, train_id):
        self.stop_commands.append(train_id)
        return SimpleNamespace(accepted=True, detail="")


class CoordinateMovementExecutionTests(unittest.TestCase):
    def planner(self):
        return CoordinateMovementPlanner(BLOCKS, EDGES, CALIBRATION)

    def test_builds_bounded_request_from_stored_calibration(self):
        movement_plan = self.planner().plan("train-7", 60, 10)

        execution = CoordinateMovementExecutionPlanner().build(movement_plan, CALIBRATION)

        self.assertEqual(execution.direction, "forward")
        self.assertEqual(execution.duration_ms, 1000)
        self.assertTrue(execution.stop_after)
        self.assertEqual(execution.stop_after_ms, 1000)
        self.assertEqual(execution.timed_request(), execution.request)
        self.assertEqual(execution.request.train_id, "train-7")

    def test_request_preserves_reverse_direction(self):
        movement_plan = self.planner().plan("train-7", 60, 10, direction="reverse")

        request = build_timed_movement_request(movement_plan, CALIBRATION)

        self.assertEqual(request.direction, "reverse")
        self.assertEqual(request.duration_ms, 1000)
        self.assertTrue(request.stop_after)

    def test_existing_planner_can_build_request_from_its_stored_calibration(self):
        movement_plan = self.planner().plan("train-7", 60, 10)

        request = self.planner().timed_request(movement_plan)

        self.assertEqual((request.direction, request.duration_ms), ("forward", 1000))

    def test_duration_is_recalculated_from_supplied_calibration(self):
        movement_plan = self.planner().plan("train-7", 60, 10)
        stale_plan = replace(movement_plan, estimated_duration_ms=1)
        stored_calibration = {"speed_kmh": 10, "duration_ms": 200, "measured_distance_mm": 100}

        request = build_timed_movement_request(stale_plan, stored_calibration)

        self.assertEqual(request.duration_ms, 1000)
        self.assertNotEqual(request.duration_ms, stale_plan.estimated_duration_ms)

    def test_calibration_history_selects_record_matching_the_plan(self):
        movement_plan = self.planner().plan("train-7", 60, 10)
        history = [
            {"speed_kmh": 8, "duration_ms": 100, "measured_distance_mm": 40},
            {"speed_kmh": 10, "duration_ms": 200, "measured_distance_mm": 100},
        ]

        execution = CoordinateMovementExecutionPlanner().build(movement_plan, history)

        self.assertEqual(execution.calibration_speed_kmh, 10)
        self.assertEqual(execution.duration_ms, 1000)

    def test_unbounded_or_zero_distance_execution_is_rejected(self):
        movement_plan = self.planner().plan("train-7", 60, 10)
        with self.assertRaisesRegex(MovementPlanValidationError, "stop after"):
            build_timed_movement_request(movement_plan, CALIBRATION, stop_after=False)

        zero_distance = replace(movement_plan, distance_mm=0)
        with self.assertRaisesRegex(MovementPlanValidationError, "distance must be positive"):
            build_timed_movement_request(zero_distance, CALIBRATION)

    def test_execution_validation_rejects_invalid_calibration_and_duration_limit(self):
        movement_plan = self.planner().plan("train-7", 60, 10)
        execution_planner = CoordinateMovementExecutionPlanner(max_duration_ms=999)
        with self.assertRaisesRegex(MovementPlanValidationError, "safety limit"):
            execution_planner.validate(movement_plan, CALIBRATION)

        with self.assertRaisesRegex(MovementPlanValidationError, "invalid stored calibration"):
            execution_planner.validate(
                movement_plan,
                {"speed_kmh": 10, "duration_ms": 0, "measured_distance_mm": 50},
            )

    def test_executor_requires_confirmation_before_any_command(self):
        execution = self.planner().execution_plan(self.planner().plan("train-7", 60, 10))
        dispatcher = FakeDispatcher()
        track = FakeTrack()
        executor = CoordinateMovementExecutor(dispatcher, track)

        with self.assertRaisesRegex(MovementExecutionError, "confirmation"):
            executor.start(execution)

        self.assertEqual(dispatcher.speed_commands, [])
        self.assertEqual(track.direction_commands, [])
        self.assertEqual(track.stop_commands, [])

    def test_executor_sets_direction_and_stops_after_timer(self):
        execution = self.planner().execution_plan(
            self.planner().plan("train-7", 60, 10, direction="reverse")
        )
        dispatcher = FakeDispatcher()
        track = FakeTrack(direction=True)
        timers = []
        executor = CoordinateMovementExecutor(
            dispatcher,
            track,
            max_speed_kmh=20,
            timer_factory=lambda seconds, callback: timers.append(FakeTimer(seconds, callback)) or timers[-1],
        )

        status = executor.start(execution, confirmed=True)

        self.assertTrue(status.running)
        self.assertEqual(track.direction_commands, [("train-7", False)])
        self.assertEqual(dispatcher.speed_commands, [("train-7", 0.5)])
        self.assertEqual(timers[0].seconds, 1.0)
        timers[0].fire()
        self.assertEqual(executor.status.state, "stopped")
        self.assertEqual(track.stop_commands, ["train-7"])
        self.assertFalse(executor.active)

    def test_executor_rejects_moving_or_non_manual_train_without_commands(self):
        execution = self.planner().execution_plan(self.planner().plan("train-7", 60, 10))
        dispatcher = FakeDispatcher(mode="automatic")
        track = FakeTrack(speed=1.0)
        executor = CoordinateMovementExecutor(dispatcher, track)

        with self.assertRaisesRegex(MovementExecutionError, "manual"):
            executor.start(execution, confirmed=True)
        self.assertEqual(dispatcher.speed_commands, [])
        self.assertEqual(track.stop_commands, [])

    def test_runtime_executor_requires_confirmation_before_commands(self):
        request = self.planner().timed_request(self.planner().plan("train-7", 60, 10))
        dispatcher = FakeDispatcher()
        track = FakeTrack()
        executor = RuntimeCoordinateMovementExecutor(dispatcher, track)

        with self.assertRaisesRegex(CoordinateExecutionError, "confirmation"):
            executor.start(request, normalized_speed=0.5)

        self.assertEqual(dispatcher.speed_commands, [])
        self.assertEqual(track.direction_commands, [])
        self.assertEqual(track.stop_commands, [])

    def test_runtime_executor_stops_track_after_injected_timer(self):
        execution = self.planner().execution_plan(self.planner().plan("train-7", 60, 10))
        dispatcher = FakeDispatcher()
        track = FakeTrack()
        timers = []
        executor = RuntimeCoordinateMovementExecutor(
            dispatcher,
            track,
            timer_factory=lambda seconds, callback: timers.append(FakeTimer(seconds, callback)) or timers[-1],
            max_speed_kmh=20,
        )

        status = executor.start(execution, confirmed=True)
        self.assertEqual(status.state, "running")
        self.assertEqual(dispatcher.speed_commands, [("train-7", 0.5)])
        self.assertEqual(timers[0].seconds, 1.0)

        timers[0].fire()

        self.assertEqual(executor.status.state, "completed")
        self.assertEqual(track.stop_commands, ["train-7"])


if __name__ == "__main__":
    unittest.main()
