"""World-clock timing and timetable catch-up use no physical transport."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.api.server import ControllerApplication, WORLD_DAY_MINUTES


class WorldClockDispatchTests(unittest.TestCase):
    def make_application(self) -> ControllerApplication:
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        for train, route, destination in zip(app.trains, (["B01", "B02"], ["B03", "B04"]), ("B02", "B04")):
            train.update(mode="automatic", route=route, destination_block_id=destination)
        app._sync_runtime_from_ui()
        app.schedules = [
            {"id": "clock-first", "time": "00:01", "train_id": "train-101", "number": "101", "dispatch_mode": "route", "route_id": "r1"},
            {"id": "clock-second", "time": "00:03", "train_id": "train-3", "number": "3", "dispatch_mode": "route", "route_id": "r2"},
        ]
        app._sync_scheduler()
        app.runtime.scheduler.reset(tick=0, world_tick=0)
        app.runtime.scheduler.start()
        return app

    def test_delayed_cycle_dispatches_departures_between_browser_refreshes(self) -> None:
        app = self.make_application()
        with patch.object(app.runtime.track, "set_train_speed", wraps=app.runtime.track.set_train_speed) as speed:
            app.tick(1, elapsed_seconds=5)
        departures = [event for event in app.events if event["type"] == "schedule_departure"]
        self.assertEqual([event["schedule_id"] for event in departures], ["clock-first", "clock-second"])
        commanded = {call.args[0] for call in speed.call_args_list if call.args[1] > 0}
        self.assertEqual(commanded, {"train-101", "train-3"})
        self.assertEqual(app.runtime.scheduler.world_current_tick, 5)

    def test_delayed_cycle_preserves_departures_across_a_complete_model_day(self) -> None:
        for elapsed, repetitions, minute in ((WORLD_DAY_MINUTES, 1, 0), (WORLD_DAY_MINUTES + 5, 2, 5), (WORLD_DAY_MINUTES * 2 + 5, 3, 5)):
            with self.subTest(elapsed=elapsed):
                app = self.make_application()
                app.tick(1, elapsed_seconds=elapsed)
                departures = [event for event in app.events if event["type"] == "schedule_departure"]
                self.assertEqual([event["schedule_id"] for event in departures], ["clock-first", "clock-second"] * repetitions)
                self.assertEqual(app.runtime.scheduler.world_current_tick, minute)

    def test_delayed_cycle_dispatches_departures_after_midnight(self) -> None:
        app = self.make_application()
        app._world_clock_seconds = (WORLD_DAY_MINUTES - 1) * 60
        app.runtime.scheduler.reset(tick=0, world_tick=WORLD_DAY_MINUTES - 1)
        app.runtime.scheduler.start()
        app.tick(1, elapsed_seconds=5)
        departures = [event for event in app.events if event["type"] == "schedule_departure"]
        self.assertEqual([event["schedule_id"] for event in departures], ["clock-first", "clock-second"])
        self.assertEqual(app.runtime.scheduler.world_current_tick, 4)

    def test_motion_clock_accounts_for_time_waiting_for_the_controller_lock(self) -> None:
        app = self.make_application()
        app._world_clock_sampled_at = 100.0

        def account_for_tick(steps: int, *, elapsed_seconds: float, clock_sampled_at: float) -> None:
            app._world_clock_seconds += elapsed_seconds * 60
            app._world_clock_sampled_at = clock_sampled_at

        with (
            patch.object(app._motion_stop, "wait", side_effect=[False, False, True]),
            patch("backend.api.server.time.monotonic", side_effect=[100, 100, 100, 100.1, 100.1, 100.1, 100.6, 100.6, 100.6, 100.6]),
            patch.object(app, "tick", side_effect=account_for_tick) as tick,
        ):
            app._motion_loop()
        self.assertEqual(tick.call_count, 2)
        self.assertAlmostEqual(tick.call_args_list[0].kwargs["elapsed_seconds"], 0.1)
        self.assertAlmostEqual(tick.call_args_list[1].kwargs["elapsed_seconds"], 0.5)
        self.assertAlmostEqual(app._world_clock_seconds, 36)


if __name__ == "__main__":
    unittest.main()
