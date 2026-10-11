"""Track ownership, colour persistence and geometry-preserving boundaries."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.api.domain_bridge import snapshot_from_ui, snapshot_to_ui
from backend.api.server import ControllerApplication
from backend.core.models import Block, LayoutSnapshot, TrackSection
from backend.infrastructure.layout_repository import snapshot_from_dict, snapshot_to_dict
from backend.services.track_geometry import cubic_controls


def cubic(a, b, c, d, t):
    return tuple((1-t)**3*a[i] + 3*(1-t)**2*t*b[i] + 3*(1-t)*t*t*c[i] + t**3*d[i] for i in (0, 1))


class TrackBlockTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()
        self.app.stop_motion_clock()
        self.addCleanup(self.app.close)

    def section(self, **updates):
        return self.app.command({"type": "set_track_section", "from": "B01", "to": "B02",
            "start_anchor_id": "B01", "end_anchor_id": "B02", **updates})

    def split(self, **updates):
        return self.app.command({"type": "add_spline_point", "from": "B01", "to": "B02",
            "start_anchor_id": "B01", "end_anchor_id": "B02", "waypoint_id": "BOUNDARY", **updates})

    def test_multiple_connections_share_one_owner_without_motion_commands(self):
        before = self.app.runtime.track.get_snapshot()
        with patch.object(self.app.runtime.track, "set_train_speed", side_effect=AssertionError("movement")):
            self.section(block_id="b01")
            self.app.command({"type": "set_track_section", "from": "B02", "to": "B03",
                "start_anchor_id": "B02", "end_anchor_id": "B03", "block_id": "B01"})
        edges = self.app._ui_edges()
        owners = [s["block_id"] for e in edges for s in e["bezier_segments"]]
        self.assertEqual(owners.count("B01"), 2)
        self.assertEqual(self.app.runtime.track.get_snapshot(), before)

    def test_unknown_or_empty_owner_is_rejected_atomically(self):
        self.section(block_id="B01", speed_limit_kmh=40)
        before = deepcopy(self.app.track_sections)
        for owner in ("MISSING", "", True, "#aabbcc"):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                self.section(block_id=owner, speed_limit_kmh=70)
            self.assertEqual(self.app.track_sections, before)

    def test_reverse_edit_keeps_owner_and_handle_orientation(self):
        self.app.command({"type": "set_track_section", "from": "B02", "to": "B01",
            "start_anchor_id": "B02", "end_anchor_id": "B01", "block_id": "B04", "control1": {"x": 11, "y": 22}})
        forward = self.app._edge_with_geometry("b01", "b02")["bezier_segments"][0]
        reverse = self.app._edge_with_geometry("b02", "b01")["bezier_segments"][0]
        self.assertEqual(forward["block_id"], reverse["block_id"])
        self.assertEqual(forward["control2"], reverse["control1"])

    def test_split_at_chosen_position_preserves_curve_owner_and_limit(self):
        self.section(block_id="B04", speed_limit_kmh=35,
            control1={"x": 60, "y": -130}, control2={"x": -40, "y": 75})
        points = [(203, 178), (453, 178)]
        old = self.app._edge_with_geometry("B01", "B02")["bezier_segments"][0]
        c1, c2 = cubic_controls(points, 0, old)
        self.split(split_fraction=.3)
        point = next(w for w in self.app.waypoints if w["id"] == "BOUNDARY")
        anchor = (point["x"], point["y"])
        geometry = [points[0], anchor, points[1]]
        sections = self.app._edge_with_geometry("B01", "B02")["bezier_segments"]
        for index, section in enumerate(sections):
            self.assertEqual(section["block_id"], "B04")
            self.assertEqual(section["speed_limit_kmh"], 35)
            a, b = cubic_controls(geometry, index, section)
            for t in (0, .2, .5, .9, 1):
                expected = cubic(points[0], c1, c2, points[1], t*.3 if index == 0 else .3+t*.7)
                actual = cubic(geometry[index], a, b, geometry[index+1], t)
                for x, y in zip(expected, actual):
                    self.assertAlmostEqual(x, y, places=8)

    def test_reverse_split_interprets_percentage_from_requested_start(self):
        self.split(start_anchor_id="B02", end_anchor_id="B01", split_fraction=.2)
        point = next(w for w in self.app.waypoints if w["id"] == "BOUNDARY")
        self.assertAlmostEqual(point["x"], cubic((203, 178), (328, 178), (328, 178), (453, 178), .8)[0])

    def test_invalid_split_is_atomic(self):
        before = (deepcopy(self.app.track_sections), deepcopy(self.app.waypoints))
        for fraction in (0, 1, float("nan"), True, -1):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                self.split(split_fraction=fraction)
            self.assertEqual((self.app.track_sections, self.app.waypoints), before)

    def test_deleting_boundary_cannot_discard_different_block_assignments(self):
        self.section(block_id="B01")
        self.split()
        self.app.command({"type": "set_track_section", "from": "B01", "to": "B02",
            "start_anchor_id": "BOUNDARY", "end_anchor_id": "B02", "block_id": "B02"})
        before = deepcopy(self.app.track_sections)
        with self.assertRaisesRegex(ValueError, "block boundary"):
            self.app.command({"type": "remove_waypoint", "waypoint_id": "BOUNDARY"})
        self.assertEqual(self.app.track_sections, before)
        self.assertTrue(any(w["id"] == "BOUNDARY" for w in self.app.waypoints))

    def test_removing_point_preserves_shared_owner_and_strictest_speed(self):
        self.section(block_id="B01", speed_limit_kmh=50)
        self.split()
        self.app.command({"type": "set_track_section", "from": "B01", "to": "B02",
            "start_anchor_id": "BOUNDARY", "end_anchor_id": "B02", "speed_limit_kmh": 20})
        self.app.command({"type": "remove_waypoint", "waypoint_id": "BOUNDARY"})
        section = self.app._edge_with_geometry("B01", "B02")["bezier_segments"][0]
        self.assertEqual((section["block_id"], section["speed_limit_kmh"]), ("B01", 20))

    def test_asset_editor_point_insertion_inherits_existing_block_and_limit(self):
        self.section(block_id="B04", speed_limit_kmh=30)
        self.app.command({"type": "add_waypoint", "waypoint": {"id": "WP_NEW", "connected_node_ids": ["B01", "B02"], "x": 330, "y": 178}})
        sections = self.app._edge_with_geometry("B01", "B02")["bezier_segments"]
        self.assertEqual(len(sections), 2)
        self.assertTrue(all((s["block_id"], s["speed_limit_kmh"]) == ("B04", 30) for s in sections))

    def test_colour_validation_happens_before_rename_or_mutation(self):
        before = deepcopy(self.app.blocks)
        for color in ("red", "#abc", "#gggggg", "url(fake)", 10):
            with self.subTest(color=color), self.assertRaises(ValueError):
                self.app.command({"type": "update_block", "block_id": "B04", "block": {"name": "Changed", "color": color}})
            self.assertEqual(self.app.blocks, before)

    def test_rename_owner_rewrites_sections_and_preserves_custom_colour(self):
        self.app.command({"type": "track_power", "enabled": False})
        self.app.command({"type": "add_block", "block": {"id": "GROUP", "name": "Shared track", "x": 900, "y": 400}})
        self.app.command({"type": "update_block", "block_id": "GROUP", "block": {"color": "#12AB34"}})
        self.section(block_id="GROUP")
        with self.assertRaisesRegex(ValueError, "track section"):
            self.app.command({"type": "remove_block", "block_id": "GROUP"})
        self.app.command({"type": "update_block", "block_id": "GROUP", "block": {"id": "SHARED"}})
        self.assertEqual(self.app.track_sections[0]["block_id"], "SHARED")
        self.assertEqual(next(b["color"] for b in self.app._ui_blocks() if b["id"] == "shared"), "#12ab34")

    def test_saved_layout_and_typed_json_round_trip(self):
        self.section(block_id="B01")
        self.app.command({"type": "update_block", "block_id": "B01", "block": {"color": "#abcdef"}})
        self.app.save_layout("track-colours")
        self.section(block_id="B03")
        self.app.load_layout("track-colours")
        self.assertEqual(self.app.track_sections[0]["block_id"], "B01")
        self.assertEqual(self.app.blocks[0]["color"], "#abcdef")
        snapshot = self.app._domain_snapshot()
        self.assertEqual(snapshot_from_dict(snapshot_to_dict(snapshot)), snapshot)
        projected = snapshot_to_ui(snapshot)
        self.assertEqual(snapshot_from_ui(edges=self.app._ui_edges(), **{k: v for k, v in projected.items() if k in {
            "blocks", "trains", "turnouts", "stations", "signals", "waypoints", "turntables", "platforms", "schedules", "routes", "scans", "connection_limits", "track_sections"}}).track_sections, snapshot.track_sections)

    def test_old_layouts_default_to_stable_direction_independent_ownership(self):
        for left, right in (("B01", "B02"), ("B02", "B01")):
            self.assertEqual(self.app._edge_with_geometry(left, right)["bezier_segments"][0]["block_id"], "B02")
        self.assertIsNone(Block("LEGACY").color)
        with self.assertRaisesRegex(ValueError, "block"):
            LayoutSnapshot(blocks=(Block("A", neighbor_ids=("B",)), Block("B", neighbor_ids=("A",))),
                track_sections=(TrackSection("A", "B", "A", "B", block_id="MISSING"),))


if __name__ == "__main__":
    unittest.main()
