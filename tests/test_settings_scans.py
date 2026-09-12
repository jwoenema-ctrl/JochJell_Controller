"""Preferences, safe wall-clock planning, and durable raster upload boundaries."""

from __future__ import annotations

import base64
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zlib

from backend.api.server import ControllerApplication, make_server, startup_z21_endpoint
from backend.core.models import BlockState
from backend.infrastructure.scan_store import MAX_SCAN_BYTES, ScanStore
from backend.infrastructure.settings import DEFAULT_SETTINGS


def png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\x88\x99\xaa" * width) * height)) + chunk(b"IEND", b""))


def upload_payload(data: bytes | None = None) -> dict[str, str]:
    return {"filename": "Yard photo.PNG", "label": "My yard", "mime_type": "image/png", "data": base64.b64encode(data if data is not None else png()).decode("ascii")}


class SettingsTests(unittest.TestCase):
    def test_settings_persist_without_changing_simulation_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "controller.sqlite3")
            app = ControllerApplication.sample(database_path=database)
            try:
                self.assertEqual(app.settings_payload()["settings"], DEFAULT_SETTINGS)
                changed = app.update_settings({"theme": "dark", "z21_host": "192.168.10.111", "z21_port": 21106, "routing": {"busy_interval_ms": 750}})
                self.assertEqual(changed["settings"]["routing"]["idle_interval_ms"], 5000)
                self.assertTrue(app.simulation_mode)
                self.assertIsNone(app.z21_host)
                self.assertFalse(changed["runtime"]["restart_required"])
                self.assertTrue(changed["runtime"]["hardware_activation_required"])
            finally:
                app.close()
            restored = ControllerApplication.sample(database_path=database)
            try:
                self.assertEqual(restored.settings_payload()["settings"], changed["settings"])
                self.assertTrue(restored.simulation_mode)
            finally:
                restored.close()

    def test_invalid_settings_are_atomic(self) -> None:
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        invalid = [
            {"theme": "neon"}, {"z21_host": "http://192.168.0.111"}, {"z21_host": "not-a-host"},
            {"z21_host": "256.0.0.1"}, {"z21_host": "::1"}, {"z21_port": 0}, {"z21_port": 65536},
            {"z21_port": True}, {"ui_refresh_ms": 999}, {"ui_refresh_ms": 60001}, {"ui_refresh_ms": 2500.5},
            {"routing": {"adaptive": "false"}}, {"routing": {"busy_interval_ms": 249}},
            {"routing": {"idle_interval_ms": 60001}}, {"routing": {"surprise": 1}}, {"routing": []},
            {"simulation_mode": False}, {"settings": []},
        ]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                app.update_settings({"theme": "dark", **item})
            self.assertEqual(app.settings_payload()["settings"], DEFAULT_SETTINGS)

    def test_settings_and_planning_never_command_or_tick_track(self) -> None:
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        before = app.runtime.track.get_snapshot()
        with ExitStack() as stack:
            for target, method in ((app.runtime.track, "tick"), (app.runtime.track, "set_train_speed"),
                                   (app.runtime.track, "stop_train"), (app.runtime.track, "set_train_route"),
                                   (app.runtime.dispatcher, "tick"), (app.runtime.connection, "check")):
                stack.enter_context(patch.object(target, method, side_effect=AssertionError(f"unexpected {method}")))
            app.update_settings({"settings": {"theme": "light", "z21_host": "10.0.0.111"}})
            self.assertTrue(app.refresh_routes(force=True))
            app.settings_payload()
        self.assertEqual(app.runtime.track.get_snapshot(), before)

    def test_physical_startup_requires_explicit_opt_in_and_honors_overrides(self) -> None:
        saved = {**DEFAULT_SETTINGS, "z21_host": "10.0.0.111", "z21_port": 21106}
        self.assertEqual(startup_z21_endpoint(saved, {}), (None, 21106))
        self.assertEqual(startup_z21_endpoint(saved, {"H0_TRACK_SYSTEM": "z21"}), ("10.0.0.111", 21106))
        self.assertEqual(startup_z21_endpoint(saved, {"H0_Z21_HOST": "10.0.0.112", "H0_Z21_PORT": "21107"}), ("10.0.0.112", 21107))
        with self.assertRaises(ValueError):
            startup_z21_endpoint(saved, {"H0_TRACK_SYSTEM": "typo"})

    def test_physical_endpoint_changes_report_restart_without_reconnecting(self) -> None:
        app = ControllerApplication.sample()
        self.addCleanup(app.close)
        # Represent an active endpoint without opening a real socket.
        app.z21_host, app.z21_port = "192.168.0.111", 21105
        with patch.dict("os.environ", {}, clear=True), patch("backend.runtime.ControllerRuntime.create_z21") as connect:
            value = app.update_settings({"z21_host": "10.0.0.111"})
            self.assertTrue(value["runtime"]["restart_required"])
            self.assertEqual(value["runtime"]["active_z21_host"], "192.168.0.111")
            connect.assert_not_called()
        with patch.dict("os.environ", {"H0_Z21_HOST": "192.168.0.111"}, clear=True):
            self.assertFalse(app.settings_payload()["runtime"]["restart_required"])
            self.assertTrue(app.settings_payload()["runtime"]["z21_environment_override"])


class RouteCadenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = ControllerApplication.sample()
        self.addCleanup(self.app.close)

    def test_busy_idle_fixed_and_updated_intervals_control_real_planning(self) -> None:
        app = self.app
        app.refresh_routes(force=True, now=100)
        count = app.settings_payload()["runtime"]["routing"]["refresh_count"]
        self.assertFalse(app.refresh_routes(now=100.9))
        self.assertTrue(app.refresh_routes(now=101.1))
        self.assertEqual(app._routing_refresh_count, count + 1)
        app.simulation_running = False
        self.assertEqual(app.settings_payload()["runtime"]["routing"]["activity"], "idle")
        self.assertFalse(app.refresh_routes(now=102.2))
        self.assertTrue(app.refresh_routes(now=106.2))
        app.update_settings({"routing": {"adaptive": False, "busy_interval_ms": 250}})
        self.assertFalse(app.refresh_routes(now=106.3))
        self.assertTrue(app.refresh_routes(now=106.5))
        self.assertEqual(app.settings_payload()["runtime"]["routing"]["effective_interval_ms"], 250)

    def test_layout_mutation_forces_refresh_before_the_interval(self) -> None:
        app = self.app
        app.update_settings({"routing": {"busy_interval_ms": 60000, "idle_interval_ms": 60000}})
        before = app._routing_refresh_count
        app.command({"type": "update_block", "block_id": "B02", "block": {"name": "Central updated"}})
        self.assertGreater(app._routing_refresh_count, before)

    def test_recalculation_excludes_out_of_service_blocks_without_motion(self) -> None:
        app = self.app
        snapshot = app.runtime.layout.snapshot().snapshot
        changed = replace(snapshot, blocks=tuple(replace(block, state=BlockState.OUT_OF_SERVICE) if block.id == "B02" else block for block in snapshot.blocks))
        app.runtime.layout.replace(changed)
        track_before = app.runtime.track.get_snapshot()
        app.refresh_routes(force=True)
        self.assertEqual(app.runtime.route_updater.desired_routes["train-101"], ("B01",))
        self.assertEqual(app.runtime.track.get_snapshot(), track_before)

    def test_background_worker_recalculates_and_stops_cleanly(self) -> None:
        app = self.app
        app.update_settings({"routing": {"adaptive": False, "busy_interval_ms": 250}})
        before, track_before = app._routing_refresh_count, app.runtime.track.get_snapshot()
        app.start_background_refresh()
        deadline = time.monotonic() + 2
        while app._routing_refresh_count == before and time.monotonic() < deadline:
            threading.Event().wait(0.02)
        worker = app._routing_thread
        app.stop_background_refresh()
        self.assertGreater(app._routing_refresh_count, before)
        self.assertFalse(worker.is_alive())
        self.assertEqual(app.runtime.track.get_snapshot(), track_before)
        self.assertFalse(app.settings_payload()["runtime"]["routing"]["running"])


class ScanUploadTests(unittest.TestCase):
    def test_supported_webp_image_and_excessive_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ScanStore(directory)
            # A real two-pixel raster fixture; no third-party decoder is needed.
            encoded = "UklGRiQAAABXRUJQVlA4IBgAAABQAQCdASoCAAIAAUAmJaQABHQAAORAAAA="
            scan, path = store.upload({"filename": "Yard.webp", "label": "WebP yard", "mime_type": "image/webp", "data": encoded})
            self.assertEqual(path.read_bytes(), base64.b64decode(encoded))
            self.assertIn("2 × 2", scan["description"])
            with self.assertRaises(ValueError):
                store.upload(upload_payload(png(width=10001, height=1)))

    def test_failed_manifest_save_rolls_back_only_new_uploaded_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = ControllerApplication.sample(database_path=str(Path(directory) / "controller.sqlite3"))
            try:
                previous = list(app.scans)
                with patch.object(app.runtime.layout_repository, "save", side_effect=RuntimeError("storage failure")), self.assertRaises(RuntimeError):
                    app.upload_scan(upload_payload())
                self.assertEqual(app.scans, previous)
                self.assertEqual(list((Path(directory) / "scans").iterdir()), [])
            finally:
                app.close()

    def test_upload_manifest_and_file_survive_restart_without_replaying_motion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "controller.sqlite3")
            app = ControllerApplication.sample(database_path=database)
            try:
                before = app.runtime.track.get_snapshot()
                with patch.object(app.runtime.track, "set_train_speed", side_effect=AssertionError("unexpected motion")):
                    result = app.upload_scan(upload_payload())
                self.assertEqual(app.runtime.track.get_snapshot(), before)
                scan = result["scan"]
                self.assertTrue(scan["image"].startswith("/api/scans/files/"))
                stored = app._scan_store.resolve(scan["image"].rsplit("/", 1)[-1])
                self.assertEqual(stored.read_bytes(), png())
            finally:
                app.close()
            restored = ControllerApplication.sample(database_path=database)
            try:
                self.assertIn(scan, restored.state()["scans"])
                self.assertEqual(restored._scan_store.resolve(stored.name), stored)
            finally:
                restored.close()

    def test_upload_rejects_paths_mismatched_types_and_oversized_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ScanStore(directory)
            for value in (
                {"filename": "../../secret.png"}, {"filename": "C:\\secret.png"}, {"filename": "image.png:stream"},
                {"filename": "photo.svg"}, {"mime_type": "image/svg+xml"}, {"mime_type": "image/jpeg"},
                {"data": "%%%"}, {"data": base64.b64encode(b"<svg onload='alert(1)'/>").decode()},
                {"label": "x" * 121}, {"data": "A" * ((((MAX_SCAN_BYTES + 2) // 3) * 4) + 4)},
            ):
                with self.subTest(value=list(value)), self.assertRaises(ValueError):
                    store.upload({**upload_payload(), **value})
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertIsNone(store.resolve("../secret.png"))
            self.assertIsNone(store.resolve("Yard photo.PNG"))

    def test_http_contract_and_protected_scan_serving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = ControllerApplication.sample(database_path=str(Path(directory) / "controller.sqlite3"))
            server = make_server("127.0.0.1", 0, app)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            def request(path: str, payload: dict | None = None):
                return urllib.request.urlopen(urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json"}), timeout=2)
            try:
                with request("/api/settings") as response:
                    self.assertEqual(json.load(response)["settings"]["theme"], "system")
                with request("/api/settings", {"theme": "dark", "ui_refresh_ms": 3000}) as response:
                    self.assertEqual(json.load(response)["settings"]["theme"], "dark")
                with request("/api/settings", {"settings": {"theme": "light"}}) as response:
                    self.assertEqual(json.load(response)["settings"]["theme"], "light")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/settings", {"z21_host": "example.com"})
                self.assertEqual(error.exception.code, 400)
                with request("/api/scans/upload", upload_payload()) as response:
                    self.assertEqual(response.status, 201)
                    scan = json.load(response)["scan"]
                with request(scan["image"]) as response:
                    self.assertEqual(response.read(), png())
                    self.assertEqual(response.headers["Content-Type"], "image/png")
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                for path in ("/api/scans/files/../controller.sqlite3", "/api/scans/files/%2e%2e%2fcontroller.sqlite3", "/api/scans/files/" + "0" * 32 + ".png"):
                    with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                        request(path)
                    self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)
                self.assertIsNone(app._routing_thread)
                app.close()
