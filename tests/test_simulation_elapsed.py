import unittest
from backend.api.server import ControllerApplication


class SimulationElapsedTests(unittest.TestCase):
    def test_minute_button_advances_one_simulated_minute(self):
        app = ControllerApplication.sample()
        try:
            before = app.runtime.scheduler.current_tick
            app.advance_simulation(60)
            self.assertAlmostEqual(app.runtime.track.get_snapshot().time_seconds, 60)
            self.assertEqual(app.runtime.scheduler.current_tick - before, 1)
            self.assertEqual(app.state()["simulation"]["clock"], "00:01:00")
            for seconds, rate in ((0, 1), (float("nan"), 1), (60, float("inf")), (601, 1)):
                with self.assertRaises(ValueError):
                    app.advance_simulation(seconds, rate)
            app.simulation_mode = False
            with self.assertRaisesRegex(ValueError, "only available"):
                app.advance_simulation(60)
        finally:
            app.close()
