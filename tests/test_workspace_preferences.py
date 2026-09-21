"""Workspace preferences are validated, durable and isolated from operation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from backend.api.server import ControllerApplication
from backend.infrastructure.settings import (
    DEFAULT_SETTINGS, DEFAULT_WORKSPACE_LAYOUT, SQLiteSettingsRepository, validate_settings,
)


class WorkspacePreferencesTests(unittest.TestCase):
    def test_old_preferences_receive_defaults(self):
        old = {key: deepcopy(value) for key, value in DEFAULT_SETTINGS.items() if key != "workspace_layout"}
        self.assertEqual(validate_settings(old)["workspace_layout"], DEFAULT_WORKSPACE_LAYOUT)
        self.assertEqual(validate_settings({"theme": "dark"}, old)["workspace_layout"], DEFAULT_WORKSPACE_LAYOUT)

    def test_partial_page_patch_preserves_other_pages_and_settings(self):
        first = validate_settings({"theme": "dark", "workspace_layout": {"pages": {"dispatch": {"sidebar_side": "right"}}}})
        order = ["node-graph", "systematic", "layout-info"]
        second = validate_settings({"workspace_layout": {"pages": {"layout": {"order": order}}}}, first)
        self.assertEqual(second["theme"], "dark")
        self.assertEqual(second["workspace_layout"]["pages"]["dispatch"]["sidebar_side"], "right")
        self.assertEqual(second["workspace_layout"]["pages"]["layout"]["order"], order + ["automation", "routes", "scans", "timetable"])
        self.assertEqual(first["workspace_layout"]["pages"]["layout"]["order"], DEFAULT_WORKSPACE_LAYOUT["pages"]["layout"]["order"])

    def test_current_panel_inventory_is_in_defaults(self):
        self.assertIn("timetable", DEFAULT_WORKSPACE_LAYOUT["pages"]["dispatch"]["order"])
        self.assertIn("automation", DEFAULT_WORKSPACE_LAYOUT["pages"]["layout"]["order"])
        self.assertIn("timetable", DEFAULT_WORKSPACE_LAYOUT["pages"]["layout"]["order"])
        self.assertIn("train-functions", DEFAULT_WORKSPACE_LAYOUT["pages"]["trains"]["sidebar_order"])

    def test_old_sidebar_preferences_receive_new_train_functions_panel(self):
        old = deepcopy(DEFAULT_WORKSPACE_LAYOUT)
        old_sidebar = ["control-center", "selected-train", "simulation", "connection-health"]
        old["pages"]["dispatch"]["sidebar_order"] = old_sidebar
        old["pages"]["trains"]["sidebar_order"] = old_sidebar
        migrated = validate_settings({}, {**DEFAULT_SETTINGS, "workspace_layout": old})
        expected = ["control-center", "selected-train", "train-functions", "simulation", "connection-health"]
        self.assertEqual(migrated["workspace_layout"]["pages"]["dispatch"]["sidebar_order"], expected)
        self.assertEqual(migrated["workspace_layout"]["pages"]["trains"]["sidebar_order"], expected)

    def test_invalid_preferences_are_atomic(self):
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        invalid = [None, [], {"unexpected": True}, {"pages": []}, {"pages": {"settings": {}}}]
        invalid += [{"pages": {"dispatch": item}} for item in [
            [], {"position": 1}, {"sidebar_side": "top"}, {"order": "node-graph"},
            {"order": ["node-graph"]}, {"order": ["layout-info", "node-graph", "systematic", "node-graph"]},
            {"order": ["layout-info", "node-graph", "systematic", {}]}, {"sidebar_order": []},
            {"order": ["layout-info", "node-graph", "systematic", "<script>"]},
        ]]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    app.update_settings({"theme": "dark", "workspace_layout": value})
                self.assertEqual(app.settings_payload()["settings"], DEFAULT_SETTINGS)

    def test_restart_persistence_reset_and_no_operational_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            app = ControllerApplication.sample(database_path=path)
            try:
                before = app.runtime.track.get_snapshot()
                desired = deepcopy(DEFAULT_WORKSPACE_LAYOUT)
                desired["pages"]["dispatch"]["sidebar_side"] = "right"
                desired["pages"]["dispatch"]["order"].reverse()
                desired["pages"]["trains"]["sidebar_order"].reverse()
                app.update_settings({"workspace_layout": desired})
                app.update_settings({"theme": "dark"})
                self.assertEqual(app.runtime.track.get_snapshot(), before)
                self.assertEqual(app.settings_payload()["settings"]["workspace_layout"], desired)
            finally:
                app.close()
            repository = SQLiteSettingsRepository(path)
            try:
                loaded = repository.load()
                self.assertEqual(loaded["workspace_layout"], desired)
                reset = validate_settings({"workspace_layout": DEFAULT_WORKSPACE_LAYOUT}, loaded)
                repository.save(reset)
                self.assertEqual(repository.load()["workspace_layout"], DEFAULT_WORKSPACE_LAYOUT)
                self.assertEqual(repository.load()["theme"], "dark")
            finally:
                repository.close()

    def test_caller_cannot_mutate_defaults(self):
        result = validate_settings({})
        result["workspace_layout"]["pages"]["layout"]["order"].reverse()
        self.assertEqual(validate_settings({})["workspace_layout"]["pages"]["layout"]["order"][0], "layout-info")


if __name__ == "__main__":
    unittest.main()
