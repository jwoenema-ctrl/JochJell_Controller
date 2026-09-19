import unittest

from backend.services.automation_recording import (
    ActionOperation,
    AutomationRecordingService,
    PlaybackPlan,
    RecordedAction,
    validate_action,
)


class AutomationRecordingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AutomationRecordingService()

    def test_start_append_stop_builds_typed_plan(self) -> None:
        self.service.start("engine", timestamp=10)
        speed = self.service.append({"type": "speed", "timestamp": 10.5, "speed": 0.75})
        direction = self.service.append({"type": "direction", "timestamp": 11, "direction": "forward"})
        function = self.service.append({"type": "function", "timestamp": 12, "function_number": 2, "enabled": True})

        plan = self.service.stop(timestamp=14)

        self.assertFalse(self.service.active)
        self.assertEqual(plan.train_id, "engine")
        self.assertEqual(plan.actions, (speed, direction, function))
        self.assertEqual(plan.action_count, 3)
        self.assertEqual(plan.duration, 4)
        self.assertEqual(function.operation, ActionOperation.FUNCTION.value)

    def test_append_accepts_action_objects_and_attaches_active_train(self) -> None:
        self.service.start("engine")
        action = self.service.append(RecordedAction(1, "speed", speed=0.25))

        self.assertEqual(action.train_id, "engine")
        self.assertEqual(action.value, 0.25)
        self.assertEqual(self.service.actions, (action,))

    def test_playback_plan_is_immutable_and_detached_from_recorder(self) -> None:
        self.service.start("engine")
        self.service.append({"type": "speed", "timestamp": 1, "value": 0.5})
        plan = self.service.stop()

        with self.assertRaises((AttributeError, TypeError)):
            plan.actions += (RecordedAction(2, "speed", speed=0.1, train_id="engine"),)
        self.assertEqual(plan.actions[0].speed, 0.5)
        self.assertEqual(self.service.actions, ())

    def test_start_append_stop_lifecycle_rejects_invalid_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "start a recording"):
            self.service.append({"type": "speed", "timestamp": 1, "speed": 0.1})
        with self.assertRaisesRegex(ValueError, "no recording"):
            self.service.stop()

        self.service.start("engine")
        with self.assertRaisesRegex(ValueError, "already active"):
            self.service.start("other")

    def test_timestamps_must_be_monotonic(self) -> None:
        self.service.start("engine", timestamp=5)
        self.service.append({"type": "speed", "timestamp": 6, "speed": 0.1})

        with self.assertRaisesRegex(ValueError, "precede"):
            self.service.append({"type": "speed", "timestamp": 5.5, "speed": 0.2})
        with self.assertRaisesRegex(ValueError, "precede"):
            self.service.stop(timestamp=5.5)

    def test_malformed_actions_are_rejected(self) -> None:
        malformed = (
            {},
            {"type": "unknown", "timestamp": 1, "value": 0},
            {"type": "speed", "timestamp": 1, "speed": 2},
            {"type": "speed", "timestamp": 1},
            {"type": "direction", "timestamp": 1, "direction": "sideways"},
            {"type": "function", "timestamp": 1, "function_number": 32, "enabled": True},
            {"type": "function", "timestamp": 1, "function_number": 1, "enabled": "yes"},
            {"type": "speed", "timestamp": float("nan"), "speed": 0.1},
            {"type": "speed", "timestamp": 1, "speed": 0.1, "extra": True},
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    validate_action(payload)

    def test_action_objects_validate_operation_specific_payloads(self) -> None:
        cases = (
            {"timestamp": 1, "operation": "speed", "speed": -0.1},
            {"timestamp": 1, "operation": "direction", "direction": "forward", "speed": 0.1},
            {"timestamp": 1, "operation": "function", "function_number": 1, "enabled": True, "direction": "forward"},
            {"timestamp": 1, "operation": "function", "function_number": True, "enabled": True},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    RecordedAction(**fields)

    def test_plan_constructor_validates_malformed_actions(self) -> None:
        action = RecordedAction(1, "speed", train_id="engine", speed=0.2)
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            PlaybackPlan("engine", (action,), 2, 3)
        with self.assertRaisesRegex(ValueError, "train_id"):
            PlaybackPlan("other", (action,), 0, 2)


if __name__ == "__main__":
    unittest.main()
