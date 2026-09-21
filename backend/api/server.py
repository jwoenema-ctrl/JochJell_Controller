"""Small dependency-free HTTP API for the local JochJell Controller dashboard.

The API deliberately keeps the browser boundary thin. Domain and hardware modules can
be swapped behind ``ControllerApplication`` without changing the frontend contract.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import dataclass, field, fields
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.api.domain_bridge import snapshot_from_ui, snapshot_to_ui
from backend.core.events import (
    BlockStateChanged,
    Event,
    FeedbackHealthChanged,
    RouteChanged,
    ScheduleStateChanged,
    SignalAspectChanged,
    TrackPowerChanged,
    TrainDatabaseChanged,
    TrainModeChanged,
    TrainPositionChanged,
    TrainSpeedChanged,
    TurnoutPositionChanged,
)
from backend.core.models import BlockState, LayoutSnapshot, ScheduleStatus, SignalAspect, TrainMode, TurnoutPosition
from backend.core.routing import RouteAlgorithm, find_route
from backend.infrastructure.train_catalogue import TrainCatalogue, export_csv, export_json, import_csv, import_json
from backend.infrastructure.train_database import DecoderFunctionMapping, MaintenanceRecord, RollingStockInventoryRecord, RollingStockRecord, TrainModel
from backend.infrastructure.settings import SQLiteSettingsRepository, validate_settings
from backend.infrastructure.wlan import WindowsRouteAPI, preflight_z21_wlan
from backend.infrastructure.scan_store import MAX_UPLOAD_BODY_BYTES, ScanStore
from backend.runtime import ControllerRuntime
from backend.services.dispatcher import ControlMode
from backend.services.connection_speed import ConnectionSpeedPolicy, next_connection
from backend.services.block_editor import block_id as validate_block_id, next_block_id, rename_references
from backend.services.scheduler import ScheduleStop as RuntimeScheduleStop
from backend.services.coordinate_move import CoordinateMovementExecutionPlanner, CoordinateMovementPlanner, MovementPlanValidationError
from backend.services.automation_recording import PlaybackPlan, RecordedAction
from backend.services.train_presence import SavedTrainPresenceService
from backend.services.pinboard import nearest_track_coordinate


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
SCAN_DIR = ROOT_DIR / "data" / "scans"


def _schedule_tick(value: Any, fallback: Any, index: int, *, default: int | None = None) -> int:
    """Convert domain stop seconds or ``HH:MM`` labels to scheduler minutes."""

    if value not in (None, ""):
        try:
            return max(0, int(round(float(value) / 60)))
        except (TypeError, ValueError):
            try:
                hour, minute = (int(part) for part in str(value).split(":", 1))
                return max(0, (hour % 24) * 60 + max(0, min(59, minute)))
            except (TypeError, ValueError):
                pass
    if fallback not in (None, ""):
        try:
            hour, minute = (int(part) for part in str(fallback).split(":", 1))
            return max(0, (hour % 24) * 60 + max(0, min(59, minute)) + index)
        except (TypeError, ValueError):
            pass
    return max(0, default if default is not None else index)


@dataclass
class ControllerApplication:
    """Application state used by both simulation and HTTP transports.

    This is intentionally small and serializable. The richer domain services remain
    replaceable behind this object as the project grows.
    """

    simulation_mode: bool = True
    connected: bool = False
    tick_count: int = 0
    track_power: bool = True
    trains: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    turnouts: list[dict[str, Any]] = field(default_factory=list)
    stations: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    waypoints: list[dict[str, Any]] = field(default_factory=list)
    turntables: list[dict[str, Any]] = field(default_factory=list)
    platforms: list[dict[str, Any]] = field(default_factory=list)
    schedules: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    feedback_occupancy: dict[str, tuple[str, ...]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    scans: list[dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": "sample-yard",
            "label": "West yard overview",
            "description": "Perspective placeholder for the first local photo scan.",
            "image": None,
            "anchor": {"x": 0.50, "y": 0.48},
        },
    ])
    simulation_running: bool = True
    connection_limits: list[dict[str, Any]] = field(default_factory=list)
    database_path: str = ":memory:"
    layout_id: str = "default"
    layout_name: str = "Sample H0 layout"
    z21_host: str | None = None
    z21_port: int = 21105
    z21_transport_profile: str = "lan"
    z21_transport_status: dict[str, Any] | None = None
    feedback_map: dict[tuple[int, int], str] = field(default_factory=dict)
    runtime: ControllerRuntime | None = field(default=None, repr=False)
    scan_directory: str | Path | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _routing_stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _routing_wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _routing_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _routing_last_monotonic: float | None = field(default=None, init=False, repr=False)
    _routing_last_at: str | None = field(default=None, init=False)
    _routing_refresh_count: int = field(default=0, init=False)
    _routing_error: str | None = field(default=None, init=False)
    _motion_stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _motion_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _scheduler_remainder_seconds: float = field(default=0.0, init=False, repr=False)
    _world_clock_seconds: float = field(default=0.0, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _presence_state: dict[str, Any] = field(default_factory=lambda: {
        "results": [],
        "summary": {"total": 0, "detected": 0, "unknown": 0, "errors": 0},
        "running": False,
        "started_at": None,
        "completed_at": None,
        "error": None,
    }, init=False, repr=False)
    _presence_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _programming_state: dict[str, Any] = field(default_factory=lambda: {
        "last_request": None,
        "last_address_request": None,
        "last_read": None,
        "supported": False,
        "detail": "Decoder CV and address programming is available when the active track transport supports it.",
    }, init=False, repr=False)
    _recording_history: list[PlaybackPlan] = field(default_factory=list, init=False, repr=False)
    _automation_programs: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _coordinate_execution_state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Compose the domain runtime once and mirror the initial UI fixture into it."""

        self._settings_repository = SQLiteSettingsRepository(self.database_path)
        self._settings = self._settings_repository.load()
        scan_directory = self.scan_directory or (Path(self.database_path).resolve().parent / "scans" if self.database_path != ":memory:" else SCAN_DIR)
        self._scan_store = ScanStore(scan_directory)
        if self.runtime is None:
            if self.z21_host:
                self.runtime = ControllerRuntime.create_z21(self.z21_host, port=self.z21_port, database_path=self.database_path, feedback_map=self.feedback_map)
                self.simulation_mode = False
            else:
                self.runtime = ControllerRuntime.create(database_path=self.database_path)
        self.runtime.connection.check()
        self._restore_formation_metadata()
        if self.z21_host:
            self.track_power = False
            for train in self.trains:
                train.update(mode="stopped", speed=0, requested_speed_kmh=0)
        self._sync_runtime_from_ui()
        self._domain_event_subscription = self.runtime.events.subscribe(Event, self._record_domain_event)
        self._last_train_blocks = {str(train.get("id")): str(train.get("block_id", "")) for train in self.trains}
        if self.database_path != ":memory:" and self.runtime.layout_repository.load(self.layout_id) is not None:
            self.load_layout(self.layout_id)

    def _restore_formation_metadata(self) -> None:
        """Load persisted locomotive pairings without replacing the UI fixture."""
        if self.runtime is None:
            return
        for train in self.trains:
            details = self.runtime.train_database.get(str(train.get("id", "")))
            metadata = dict(details.metadata) if details is not None else {}
            if "graph_enabled" in metadata:
                train["graph_enabled"] = bool(metadata["graph_enabled"])
            raw_ids = metadata.get("locomotive_ids", ())
            if isinstance(raw_ids, (list, tuple)):
                train["locomotive_ids"] = [self._canonical_train_id(str(item)) for item in raw_ids if str(item)]
            if not train.get("consist") and isinstance(metadata.get("consist"), list):
                train["consist"] = deepcopy(metadata["consist"])
        for train in self.trains:
            for raw_id in train.get("locomotive_ids", ()):
                member_id = self._canonical_train_id(str(raw_id))
                member = next((item for item in self.trains if str(item.get("id")) == member_id), None)
                if member is not None and member is not train:
                    member["coupled_to"] = str(train.get("id"))

    @classmethod
    def sample(
        cls,
        *,
        database_path: str = ":memory:",
        z21_host: str | None = None,
        z21_port: int = 21105,
        z21_transport_profile: str = "lan",
        z21_transport_status: dict[str, Any] | None = None,
        feedback_map: dict[tuple[int, int], str] | None = None,
    ) -> "ControllerApplication":
        return cls(
            trains=[
                {
                    "id": "train-101",
                    "name": "BR 218 + freight",
                    "address": 101,
                    "mode": "automatic",
                    "speed": 42,
                    "direction": "forward",
                    "block_id": "B01",
                    "length_mm": 1420,
                    "manufacturer": "Fleischmann",
                    "model_number": "428001",
                },
                {
                    "id": "train-3",
                    "name": "ICE 3",
                    "address": 3,
                    "mode": "manual",
                    "speed": 0,
                    "direction": "forward",
                    "block_id": "B03",
                    "length_mm": 1980,
                    "manufacturer": "Roco",
                    "model_number": "63100",
                },
            ],
            blocks=[
                {"id": "B01", "name": "West approach", "x": 140, "y": 150, "occupied_by": "train-101", "status": "occupied", "neighbor_ids": ["B02"]},
                {"id": "B02", "name": "Central station", "x": 390, "y": 150, "occupied_by": None, "status": "free", "neighbor_ids": ["B01", "B03"]},
                {"id": "B03", "name": "East platform", "x": 640, "y": 150, "occupied_by": "train-3", "status": "occupied", "neighbor_ids": ["B02", "B04"]},
                {"id": "B04", "name": "Yard", "x": 390, "y": 360, "occupied_by": None, "status": "free", "neighbor_ids": ["B03"]},
            ],
            turnouts=[
                {"id": "T01", "name": "Central turnout", "address": 1, "from": "B02", "to": "B03", "alternate": "B04", "state": "straight"},
            ],
            stations=[
                {"id": "ST01", "name": "Central station", "blockIds": ["B02"], "platformIds": ["P01"]},
                {"id": "ST02", "name": "East platform", "blockIds": ["B03"], "platformIds": ["P02"]},
            ],
            signals=[
                {"id": "S01", "name": "West departure", "address": 10, "block_id": "B01", "protects_block_id": "B02", "aspect": "green"},
                {"id": "S02", "name": "Central exit", "address": 11, "block_id": "B02", "protects_block_id": "B03", "aspect": "red"},
            ],
            waypoints=[
                {"id": "WP01", "name": "Central throat", "connected_node_ids": ["B02", "B04"], "x": 390, "y": 290},
            ],
            turntables=[
                {"id": "TT01", "name": "Yard turntable", "address": 44, "connected_block_ids": ["B04"], "aligned_block_id": "B04", "x": 570, "y": 300},
            ],
            platforms=[
                {"id": "P01", "name": "Central station 1", "stationId": "ST01", "blockId": "B02", "lengthMm": 2200, "blockIds": ["b02"]},
                {"id": "P02", "name": "East platform 2", "stationId": "ST02", "blockId": "B03", "lengthMm": 1980, "blockIds": ["b03"]},
            ],
            schedules=[
                {"id": "s1", "time": "10:45", "service": "BR 218 + freight", "number": "101", "route": "West approach  →  Central station", "platform": "P01", "state": "On time"},
                {"id": "s2", "time": "10:48", "service": "ICE 3", "number": "3", "station_id": "ST02", "route": "East platform  →  Central station", "platform": "P02", "state": "Ready"},
            ],
            routes=[
                {"id": "r1", "name": "West approach to Central", "source_block_id": "B01", "target_block_id": "B02", "node_ids": ["B01", "B02"], "algorithm": "a_star", "enabled": True},
                {"id": "r2", "name": "East platform to Yard", "source_block_id": "B03", "target_block_id": "B04", "node_ids": ["B03", "B04"], "algorithm": "a_star", "enabled": True},
            ],
            database_path=database_path,
            z21_host=z21_host,
            z21_port=z21_port,
            z21_transport_profile=z21_transport_profile,
            z21_transport_status=deepcopy(z21_transport_status),
            feedback_map=dict(feedback_map or {}),
        )

    def close(self) -> None:
        """Safely power down the track, then close runtime resources.

        Shutdown is deliberately best-effort.  The Z21 may already be offline
        when the window closes, but that must never leave the application open
        behind a confirmation dialog or prevent its sockets and databases from
        being released.
        """

        with self._lock:
            if self._closed:
                return
            self._closed = True
            runtime = self.runtime

        # Do not hold the application lock while joining workers: a worker can
        # be finishing a tick while waiting for this same lock.
        try:
            self.stop_motion_clock()
        except Exception:
            pass
        try:
            self.stop_background_refresh()
        except Exception:
            pass
        worker = self._presence_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=0.2)
        self._presence_thread = None
        try:
            if runtime is not None:
                try:
                    runtime.dispatcher.emergency_stop()
                except Exception:
                    pass
                try:
                    # This is the decisive hardware shutdown packet.  It is
                    # attempted even when the cached connection is stale.
                    runtime.track.set_power(False)
                except Exception:
                    pass
                self.track_power = False
        finally:
            subscription = getattr(self, "_domain_event_subscription", None)
            if subscription is not None:
                subscription.close()
                self._domain_event_subscription = None
            if runtime is not None:
                try:
                    runtime.close()
                finally:
                    self.runtime = None
            repository = getattr(self, "_settings_repository", None)
            if repository is not None:
                repository.close()
                self._settings_repository = None

    def _routing_activity(self) -> str:
        if self.runtime is None or not self.track_power or (self.simulation_mode and not self.simulation_running):
            return "idle"
        snapshot = self.runtime.track.get_snapshot()
        moving = any(motion.speed > 0 or motion.target_speed > 0 for motion in snapshot.trains)
        scheduled = any(self._schedule_domain_status(row.get("state")) is ScheduleStatus.ACTIVE for row in self.schedules)
        return "busy" if moving or scheduled else "idle"

    def _routing_interval_ms(self) -> int:
        routing = self._settings["routing"]
        key = "idle_interval_ms" if routing["adaptive"] and self._routing_activity() == "idle" else "busy_interval_ms"
        return routing[key]

    def settings_payload(self) -> dict[str, Any]:
        """Read saved preferences and live status, without probing any device."""

        with self._lock:
            next_host = os.environ.get("H0_Z21_HOST") or self._settings["z21_host"]
            next_port = int(os.environ.get("H0_Z21_PORT") or self._settings["z21_port"])
            next_profile = "wlan" if self._settings["z21_wlan_enabled"] else "lan"
            active_profile = self.z21_transport_profile if self.z21_host else "simulation"
            restart_required = bool(self.z21_host and (
                self.z21_host != next_host
                or self.z21_port != next_port
                or active_profile != next_profile
            ))
            transport_status = deepcopy(self.z21_transport_status) if self.z21_host else {
                "profile": "simulation",
                "state": "inactive",
                "ready": True,
                "host": None,
                "detail": "Simulation does not open a physical network transport.",
            }
            if self.z21_host and transport_status is None:
                transport_status = {
                    "profile": active_profile,
                    "state": "unknown",
                    "ready": False,
                    "host": self.z21_host,
                    "detail": "No startup transport preflight status is available.",
                }
            interval = self._routing_interval_ms()
            remaining = max(0, interval - int((time.monotonic() - self._routing_last_monotonic) * 1000)) if self._routing_last_monotonic is not None else 0
            return {
                "settings": deepcopy(self._settings),
                "runtime": {
                    "connection_mode": "z21" if self.z21_host else "simulation",
                    "active_z21_host": self.z21_host,
                    "active_z21_port": self.z21_port if self.z21_host else None,
                    "next_z21_host": next_host,
                    "next_z21_port": next_port,
                    "transport_profile": active_profile,
                    "next_transport_profile": next_profile,
                    "transport_status": transport_status,
                    "z21_environment_override": bool(os.environ.get("H0_Z21_HOST") or os.environ.get("H0_Z21_PORT")),
                    "restart_required": restart_required,
                    "hardware_activation_required": not bool(self.z21_host),
                    "connection_message": "Saved for the next explicit physical startup; simulation stays active." if not self.z21_host else "Restart physical control to apply the saved endpoint or transport profile." if restart_required else f"Physical {active_profile.upper()} profile is active. Environment endpoint overrides take precedence when set.",
                    "routing": {
                        "running": bool(self._routing_thread and self._routing_thread.is_alive()),
                        "activity": self._routing_activity(),
                        "adaptive": self._settings["routing"]["adaptive"],
                        "effective_interval_ms": interval,
                        "next_refresh_in_ms": remaining,
                        "refresh_count": self._routing_refresh_count,
                        "last_refresh_at": self._routing_last_at,
                        "error": self._routing_error,
                        "motion_commands_enabled": False,
                    },
                },
            }

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            patch = payload.get("settings", payload)
            validated = validate_settings(patch, self._settings)
            self._settings = self._settings_repository.save(validated)
            self._routing_wake.set()
            return self.settings_payload()

    def refresh_routes(self, *, force: bool = False, now: float | None = None) -> bool:
        """Run a due planning cycle. No simulation or movement is advanced."""

        with self._lock:
            if self.runtime is None:
                return False
            current_time = time.monotonic() if now is None else now
            if not force and self._routing_last_monotonic is not None and (current_time - self._routing_last_monotonic) * 1000 < self._routing_interval_ms():
                return False
            destinations = {str(train["id"]): str(train["destination_block_id"]) for train in self.trains if train.get("destination_block_id")}
            positions = {str(train["id"]): str(train.get("block_id", "")) for train in self.trains}
            routes = self.runtime.refresh_routes(destinations, positions)
            for train in self.trains:
                if str(train["id"]) in routes:
                    train["route"] = list(routes[str(train["id"])])
            self._routing_last_monotonic = current_time
            self._routing_last_at = datetime.now(timezone.utc).isoformat()
            self._routing_refresh_count += 1
            self._routing_error = None
            return True

    def start_background_refresh(self) -> None:
        with self._lock:
            if self._routing_thread and self._routing_thread.is_alive():
                return
            self._routing_stop.clear()
            self._routing_wake.clear()
            self._routing_thread = threading.Thread(target=self._routing_loop, name="h0-route-refresh", daemon=True)
            self._routing_thread.start()

    def start_motion_clock(self) -> None:
        """One clock per application, independent of browser tabs and route planning."""
        with self._lock:
            if self._motion_thread and self._motion_thread.is_alive():
                return
            self._motion_stop.clear()
            self._motion_thread = threading.Thread(target=self._motion_loop, name="h0-motion", daemon=True)
            self._motion_thread.start()

    def _motion_loop(self) -> None:
        interval = self.runtime.track.tick_seconds if self.simulation_mode else 1.0
        next_tick = time.monotonic() + interval
        while not self._motion_stop.wait(max(0, next_tick - time.monotonic())):
            try:
                with self._lock:
                    if self.track_power and (not self.simulation_mode or self.simulation_running):
                        self.tick(1, elapsed_seconds=interval)
                next_tick += interval
                if next_tick < time.monotonic() - interval:
                    # Never burst hardware commands after a suspended computer.
                    next_tick = time.monotonic() + interval
            except Exception as exc:
                with self._lock:
                    self.simulation_running = False
                    self.events.append({"type": "motion_clock_error", "detail": str(exc)})
                    self.runtime.dispatcher.emergency_stop()
                return

    def stop_motion_clock(self) -> None:
        self._motion_stop.set()
        worker = self._motion_thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError("motion controller did not stop")
        self._motion_thread = None

    def _routing_loop(self) -> None:
        while not self._routing_stop.is_set():
            # Clear before planning so a concurrent settings/layout update
            # always wakes the next wait rather than getting lost.
            self._routing_wake.clear()
            try:
                self.refresh_routes()
            except Exception as exc:
                with self._lock:
                    self._routing_error = str(exc)
                    self._routing_last_monotonic = time.monotonic()
            with self._lock:
                elapsed = time.monotonic() - (self._routing_last_monotonic or time.monotonic())
                delay = max(0.01, self._routing_interval_ms() / 1000 - elapsed)
            self._routing_wake.wait(delay)

    def stop_background_refresh(self) -> None:
        self._routing_stop.set()
        self._routing_wake.set()
        worker = self._routing_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError("route planner did not stop; persistence remains open for safety")
        self._routing_thread = None

    def _persist_scan_manifest(self) -> None:
        """Save scans via the existing layout store without replaying train commands."""

        if self.runtime is None:
            raise RuntimeError("runtime is not available")
        snapshot = self._domain_snapshot()
        self.runtime.layout_repository.save(self.layout_id, snapshot, name=self.layout_name)
        self.runtime.layout.replace(snapshot)

    def upload_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            scan, path = self._scan_store.upload(payload)
            self.scans.append(scan)
            try:
                self._persist_scan_manifest()
            except Exception:
                self.scans.remove(scan)
                path.unlink(missing_ok=True)
                raise
            self.events.append({"type": "scan_uploaded", "scan_id": scan["id"]})
            return {"scan": deepcopy(scan), "scans": deepcopy(self.scans)}

    def _record_domain_event(self, event: Event) -> None:
        """Project typed domain events into the bounded HTTP event history."""

        def value_for_json(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, tuple):
                return [value_for_json(item) for item in value]
            if isinstance(value, list):
                return [value_for_json(item) for item in value]
            if isinstance(value, dict):
                return {str(key): value_for_json(item) for key, item in value.items()}
            return value

        event_name = re.sub(r"(?<!^)(?=[A-Z])", "_", event.__class__.__name__).lower()
        serialized = {item.name: value_for_json(getattr(event, item.name)) for item in fields(event)}
        self.events.append({"type": event_name, **serialized})

    def _publish_domain_event(self, event: Event) -> None:
        """Publish one typed event when the composed runtime is available."""

        if self.runtime is not None:
            self.runtime.events.publish(event)

    @staticmethod
    def _schedule_domain_status(value: Any) -> ScheduleStatus:
        """Normalize the UI's friendly schedule labels to the domain enum."""

        normalized = str(value or "planned").strip().lower().replace(" ", "_")
        if normalized in {"active", "running", "departed", "boarding"}:
            return ScheduleStatus.ACTIVE
        if normalized in {"paused", "hold"}:
            return ScheduleStatus.PAUSED
        if normalized in {"completed", "complete", "arrived"}:
            return ScheduleStatus.COMPLETED
        if normalized in {"cancelled", "canceled"}:
            return ScheduleStatus.CANCELLED
        return ScheduleStatus.PLANNED

    def _domain_snapshot(self) -> LayoutSnapshot:
        return snapshot_from_ui(
            blocks=self.blocks,
            turnouts=self.turnouts,
            trains=self.trains,
            schedules=self.schedules,
            routes=self.routes,
            edges=self._topology_edges(),
            stations=self.stations,
            signals=self.signals,
            waypoints=self.waypoints,
            turntables=self.turntables,
            platforms=self.platforms,
            scans=self.scans,
            connection_limits=self.connection_limits,
            revision=self.runtime.layout.snapshot().version if self.runtime is not None else 0,
        )

    def _sync_runtime_from_ui(self, *, apply_motion: bool = True) -> None:
        """Keep the typed runtime aligned with the current display fixture."""

        if self.runtime is None:
            return
        snapshot = self._domain_snapshot()
        self.runtime.layout.replace(snapshot)
        graph = self.runtime.layout.graph()
        self._apply_speed_policy(snapshot)
        self.runtime.dispatcher.set_graph(graph)
        desired_train_ids = {str(train["id"]) for train in self.trains}
        for existing_id in tuple(self.runtime.dispatcher.trains):
            if existing_id not in desired_train_ids:
                if hasattr(self.runtime.track, "remove_train"):
                    self.runtime.track.remove_train(existing_id)
                self.runtime.dispatcher.unregister_train(existing_id)
        for train in self.trains:
            train_id = str(train["id"])
            block_id = str(train.get("block_id", "B01"))
            if not train.get("graph_enabled", True):
                if train_id in self.runtime.dispatcher.trains:
                    if hasattr(self.runtime.track, "remove_train"):
                        self.runtime.track.remove_train(train_id)
                    self.runtime.dispatcher.unregister_train(train_id)
                continue
            if self.z21_host and train.get("address") in (None, ""):
                # A catalogue record may be known before a decoder address is
                # assigned. Keep it in the database/UI, but never register an
                # unaddressed model with the physical command station.
                if train_id in self.runtime.dispatcher.trains:
                    if hasattr(self.runtime.track, "remove_train"):
                        self.runtime.track.remove_train(train_id)
                    self.runtime.dispatcher.unregister_train(train_id)
                continue
            if self.z21_host and hasattr(self.runtime.track, "register_train"):
                # A physical train may have been created before its decoder
                # address was entered. Re-bind on every sync so a later edit
                # reaches the live Z21 adapter, including address changes.
                self.runtime.track.register_train(
                    train_id,
                    int(train["address"]),
                    forward=str(train.get("direction", "forward")).lower() != "reverse",
                )
            current_motion = next((motion for motion in self.runtime.track.get_snapshot().trains if motion.train_id == train_id), None)
            if current_motion is not None and current_motion.block_id != block_id and hasattr(self.runtime.track, "remove_train"):
                self.runtime.track.remove_train(train_id)
                self.runtime.dispatcher.unregister_train(train_id)
            if train_id not in self.runtime.dispatcher.trains:
                route = tuple(str(item).upper() for item in train.get("route", ()) if str(item))
                if not route:
                    goal_id = next((block.id for block in reversed(snapshot.blocks) if graph.node(block.id) is not None), block_id)
                    planned = find_route(graph, block_id.upper(), goal_id, algorithm=RouteAlgorithm.A_STAR) if graph.node(block_id.upper()) is not None else None
                    route = planned.node_ids if planned is not None else (block_id,)
                self.runtime.add_train(train_id, block_id, route=route, address=train.get("address"))
            mode_value = str(train.get("mode", "manual")).lower()
            mode = ControlMode.AUTOMATIC if mode_value == "automatic" else ControlMode.STOPPED if mode_value in {"stopped", "safe", "stop"} else ControlMode.MANUAL
            reserve_route = mode is ControlMode.AUTOMATIC or bool(train.get("target_coordinate"))
            if not reserve_route:
                self.runtime.route_updater.release_train(train_id)
            desired_route = (
                tuple(str(item).upper() for item in train.get("route", ()) if str(item))
                or tuple(self.runtime.route_updater.desired_routes.get(train_id, ()))
            ) if reserve_route else ()
            route_usable = all(
                graph.node(left) is not None
                and any(edge.target_id == right for edge in graph.neighbors(left))
                for left, right in zip(desired_route, desired_route[1:])
            )
            route_replanned = True
            if len(desired_route) > 1 and not route_usable:
                destination_id = str(train.get("destination_block_id") or desired_route[-1]).upper()
                if graph.node(block_id.upper()) is not None and graph.node(destination_id) is not None:
                    planned = find_route(graph, block_id.upper(), destination_id, algorithm=RouteAlgorithm.A_STAR)
                    if planned is not None:
                        desired_route = planned.node_ids
                    else:
                        desired_route = (block_id.upper(),)
                        route_replanned = False
                else:
                    desired_route = (block_id.upper(),)
                    route_replanned = False
            if desired_route:
                self.runtime.route_updater.set_route(train_id, desired_route)
                if hasattr(self.runtime.track, "set_train_route"):
                    self.runtime.track.set_train_route(train_id, desired_route)
                if mode is ControlMode.AUTOMATIC:
                    train["route"] = list(desired_route)
                    train.setdefault("destination_block_id", desired_route[-1])
            if not apply_motion:
                continue
            if self.z21_host:
                # A physical layout is observed/commanded only after the user
                # sends an explicit UI command; startup should not move trains.
                self.runtime.dispatcher.register_train(train_id, mode=mode)
                continue
            self.runtime.dispatcher.set_mode(train_id, mode)
            if mode is ControlMode.STOPPED:
                continue
            normalized = max(0.0, min(1.0, float(train.get("requested_speed_kmh", train.get("speed", 0))) / max(1.0, float(train.get("maxSpeed", train.get("max_speed_kmh", 140))))))
            if mode is ControlMode.AUTOMATIC:
                self.runtime.dispatcher.automatic_speed(train_id, normalized)
            else:
                self.runtime.dispatcher.manual_speed(train_id, normalized)
            if mode is ControlMode.AUTOMATIC and not route_replanned:
                self.runtime.track.stop_train(train_id)
                train["speed"] = 0
        self._sync_train_database()
        self._sync_scheduler()
        self.refresh_routes(force=True)
        self._routing_wake.set()

    def _sync_scheduler(self) -> None:
        """Project timetable rows into the deterministic scheduler service."""

        if self.runtime is None:
            return
        current_tick = self.runtime.scheduler.current_tick
        current_world_tick = getattr(self.runtime.scheduler, "world_current_tick", current_tick)
        was_running = self.runtime.scheduler.running
        self.runtime.scheduler.clear()
        for row in self.schedules:
            schedule_id = str(row.get("id", "")).strip()
            number = str(row.get("number", "")).strip()
            train_id = next((str(train["id"]) for train in self.trains if str(train.get("address", "")) == number), self._canonical_train_id(row.get("train_id")))
            if not schedule_id or not train_id:
                continue
            raw_stops = row.get("stops")
            if isinstance(raw_stops, (list, tuple)) and raw_stops:
                for index, raw_stop in enumerate(raw_stops):
                    if not isinstance(raw_stop, dict):
                        continue
                    station_id = str(raw_stop.get("station_id", raw_stop.get("stationId", row.get("station_id", self.stations[0].get("id", "ST01") if self.stations else "ST01"))))
                    arrival_tick = _schedule_tick(raw_stop.get("arrival_seconds", raw_stop.get("arrivalSeconds")), row.get("time", "00:00"), index)
                    departure_tick = _schedule_tick(raw_stop.get("departure_seconds", raw_stop.get("departureSeconds")), None, index, default=arrival_tick + 1)
                    if station_id:
                        stop_id = schedule_id if index == 0 else f"{schedule_id}#{index}"
                        self.runtime.scheduler.add_stop(RuntimeScheduleStop(stop_id, train_id, station_id, arrival_tick, max(arrival_tick, departure_tick), str(raw_stop.get("platform_id", raw_stop.get("platformId", row.get("platform", "")))) or None))
            else:
                station_id = str(row.get("station_id", self.stations[0].get("id", "ST01") if self.stations else "ST01"))
                arrival_tick = _schedule_tick(None, row.get("time", "00:00"), 0)
                self.runtime.scheduler.add_stop(RuntimeScheduleStop(schedule_id, train_id, station_id, arrival_tick, arrival_tick + 1, str(row.get("platform", "")) or None))
        if was_running or self.simulation_running:
            self.runtime.scheduler.start(tick=current_tick, world_tick=current_world_tick)

    def _apply_speed_policy(self, snapshot: LayoutSnapshot) -> None:
        try:
            self.runtime.track.configure_speed_limits(ConnectionSpeedPolicy(snapshot.connection_limits,
                {train.id: train.max_speed_kmh for train in snapshot.trains}))
        except Exception:
            self.runtime.dispatcher.emergency_stop()
            for train in self.trains:
                train.update(mode="stopped", speed=0, requested_speed_kmh=0)
            raise

    def _sync_train_database(self) -> None:
        """Persist the editable model/decode fields in the runtime database."""

        if self.runtime is None:
            return
        for train in self.trains:
            database = self.runtime.train_database
            train_id = str(train["id"])
            database.upsert(
                TrainModel(
                    train_id=train_id,
                    name=str(train.get("name", train_id)),
                    manufacturer=str(train.get("manufacturer", "")),
                    model=str(train.get("model_number", train.get("model", ""))),
                    scale="H0",
                    decoder_address=int(train["address"]) if train.get("address") not in (None, "") else None,
                    decoder_protocol=str(train.get("decoder_protocol", "DCC")),
                    era=str(train.get("era", "")),
                    length_mm=float(train.get("length_mm", train.get("length", 0)) or 0),
                    mass_g=float(train["mass_g"]) if train.get("mass_g") not in (None, "") else None,
                    max_speed_kmh=float(train.get("maxSpeed", train.get("max_speed_kmh", 140)) or 0),
                    metadata={
                        "origin": train.get("origin", ""),
                        "destination": train.get("destination", ""),
                        "consist": train.get("consist", []),
                        "locomotive_ids": list(train.get("locomotive_ids", ())),
                        "graph_enabled": bool(train.get("graph_enabled", True)),
                    },
                )
            )
            consist = list(train.get("consist", ()))
            desired_vehicle_ids: set[str] = set()
            for index, item in enumerate(consist):
                if not isinstance(item, dict):
                    continue
                vehicle_id = str(
                    item.get("id")
                    or item.get("vehicle_id")
                    or item.get("rolling_stock_id")
                    or f"{train_id}-vehicle-{index + 1}"
                ).strip()
                if not vehicle_id:
                    continue
                desired_vehicle_ids.add(vehicle_id)
                database.upsert_rolling_stock(
                    RollingStockRecord(
                        train_id=train_id,
                        rolling_stock_id=vehicle_id,
                        position=index,
                        vehicle_type=str(item.get("type", item.get("vehicle_type", "vehicle"))),
                        name=str(item.get("name", "")),
                        manufacturer=str(item.get("manufacturer", "")),
                        model=str(item.get("model", item.get("model_number", ""))),
                        length_mm=float(item["length_mm"]) if item.get("length_mm") not in (None, "") else None,
                        mass_g=float(item["mass_g"]) if item.get("mass_g") not in (None, "") else None,
                        metadata={key: value for key, value in item.items() if key not in {"id", "vehicle_id", "rolling_stock_id", "type", "vehicle_type", "name", "manufacturer", "model", "model_number", "length_mm", "mass_g"}},
                    )
                )
            for record in database.list_rolling_stock(train_id):
                if record.rolling_stock_id not in desired_vehicle_ids:
                    database.delete_rolling_stock(train_id, record.rolling_stock_id)
            raw_functions = train.get("decoder_functions", {})
            function_items = raw_functions.items() if isinstance(raw_functions, dict) else enumerate(raw_functions if isinstance(raw_functions, (list, tuple)) else ())
            for function_number, value in function_items:
                if isinstance(value, dict):
                    mapping = DecoderFunctionMapping(
                        train_id=train_id,
                        function_number=int(value.get("function_number", function_number)),
                        name=str(value.get("name", value.get("function_name", "Function"))),
                        description=str(value.get("description", "")),
                        momentary=bool(value.get("momentary", False)),
                        enabled=bool(value.get("enabled", True)),
                        metadata=dict(value.get("metadata", {})),
                    )
                else:
                    mapping = DecoderFunctionMapping(train_id, int(function_number), str(value))
                database.upsert_decoder_function(mapping)

    def train_database(self, train_id: str | None = None) -> list[dict[str, Any]] | dict[str, Any] | None:
        """Return all model metadata or one train record for the UI/API."""

        if self.runtime is None:
            return [] if train_id is None else None
        records = self.runtime.train_database.list()
        def serialize(record: TrainModel) -> dict[str, Any]:
            details = self.runtime.train_database.get_full_train(record.train_id)
            return {
                "train_id": record.train_id,
                "name": record.name,
                "manufacturer": record.manufacturer,
                "model": record.model,
                "scale": record.scale,
                "decoder_address": record.decoder_address,
                "decoder_protocol": record.decoder_protocol,
                "era": record.era,
                "length_mm": record.length_mm,
                "mass_g": record.mass_g,
                "max_speed_kmh": record.max_speed_kmh,
                "metadata": dict(record.metadata),
                "decoder_functions": [
                    {
                        "function_number": item.function_number,
                        "name": item.name,
                        "description": item.description,
                        "momentary": item.momentary,
                        "enabled": item.enabled,
                        "metadata": dict(item.metadata),
                    }
                    for item in (details.decoder_functions if details is not None else ())
                ],
                "maintenance_records": [
                    {
                        "record_id": item.record_id,
                        "service_date": item.service_date,
                        "service_type": item.service_type,
                        "description": item.description,
                        "mileage_km": item.mileage_km,
                        "cost": item.cost,
                        "performed_by": item.performed_by,
                        "next_service_date": item.next_service_date,
                        "metadata": dict(item.metadata),
                    }
                    for item in (details.maintenance_records if details is not None else ())
                ],
                "rolling_stock": [
                    {
                        "rolling_stock_id": item.rolling_stock_id,
                        "vehicle_id": item.rolling_stock_id,
                        "position": item.position,
                        "vehicle_type": item.vehicle_type,
                        "name": item.name,
                        "manufacturer": item.manufacturer,
                        "model": item.model,
                        "length_mm": item.length_mm,
                        "mass_g": item.mass_g,
                        "metadata": dict(item.metadata),
                    }
                    for item in (details.rolling_stock if details is not None else ())
                ],
                "calibrations": [
                    {
                        "calibration_id": item.calibration_id,
                        "speed_kmh": item.speed_kmh,
                        "duration_ms": item.duration_ms,
                        "measured_distance_mm": item.measured_distance_mm,
                        "created_at": item.created_at,
                        "notes": item.notes,
                    }
                    for item in (details.calibrations if details is not None else ())
                ],
            }
        if train_id is not None:
            record = self.runtime.train_database.get(self._canonical_train_id(str(train_id)))
            return serialize(record) if record is not None else None
        return [serialize(record) for record in records]

    def calibration_state(self) -> dict[str, Any]:
        """Return the active calibration run and stored measurements."""

        run = self.runtime.calibration.run if self.runtime is not None else None
        history = self.runtime.calibration.history() if self.runtime is not None else ()
        return {
            "active": None if run is None else {
                "run_id": run.run_id, "train_id": self._ui_train_id(run.train_id),
                "speed_kmh": run.speed_kmh, "duration_ms": run.duration_ms,
                "status": run.status, "started_at": run.started_at,
                "stopped_at": run.stopped_at, "error": run.error,
            },
            "history": [
                {
                    "calibration_id": item.calibration_id,
                    "train_id": self._ui_train_id(item.train_id),
                    "speed_kmh": item.speed_kmh,
                    "duration_ms": item.duration_ms,
                    "measured_distance_mm": item.measured_distance_mm,
                    "created_at": item.created_at,
                    "notes": item.notes,
                }
                for item in history
            ],
        }

    def train_presence_state(self) -> dict[str, Any]:
        return deepcopy(self._presence_state)

    def rolling_stock_inventory(self) -> dict[str, Any]:
        """Return a fleet-wide rolling-stock inventory derived from saved consists."""
        stored = self.runtime.train_database.list_inventory() if self.runtime is not None else ()
        if stored:
            rows = [
                {
                    "id": item.item_id, "name": item.name, "vehicle_type": item.vehicle_type,
                    "manufacturer": item.manufacturer, "model": item.model, "count": item.quantity,
                    "train_ids": [], "length_mm": item.length_mm, "mass_g": item.mass_g,
                }
                for item in stored
            ]
            return {"total": sum(item.quantity for item in stored), "distinct": len(rows), "items": rows, "source": "inventory"}
        grouped: dict[str, dict[str, Any]] = {}
        total = 0
        for train in self.trains:
            database = train.get("database") if isinstance(train.get("database"), dict) else {}
            consist = train.get("rolling_stock") or database.get("rolling_stock") or train.get("consist") or ()
            for item in consist:
                if not isinstance(item, dict):
                    continue
                vehicle_id = str(item.get("catalogue_id") or item.get("rolling_stock_id") or item.get("id") or item.get("name") or "vehicle").strip()
                vehicle_type = str(item.get("vehicle_type") or item.get("type") or "rolling stock").strip().lower()
                key = f"{vehicle_type}:{vehicle_id.lower()}"
                row = grouped.setdefault(key, {
                    "id": vehicle_id,
                    "name": str(item.get("name") or vehicle_id),
                    "vehicle_type": vehicle_type,
                    "manufacturer": str(item.get("manufacturer") or ""),
                    "model": str(item.get("model") or item.get("model_number") or ""),
                    "count": 0,
                    "train_ids": [],
                    "length_mm": item.get("length_mm"),
                    "mass_g": item.get("mass_g"),
                })
                row["count"] += 1
                train_id = str(train.get("id", ""))
                if train_id and train_id not in row["train_ids"]:
                    row["train_ids"].append(train_id)
                total += 1
        rows = sorted(grouped.values(), key=lambda row: (row["vehicle_type"], row["name"].lower(), row["id"]))
        return {"total": total, "distinct": len(rows), "items": rows}

    def programming_state(self) -> dict[str, Any]:
        return deepcopy(self._programming_state)

    @staticmethod
    def _recording_action_payload(action: RecordedAction) -> dict[str, Any]:
        return {"timestamp": action.timestamp, "operation": str(action.operation), "train_id": action.train_id,
                "speed": action.speed, "direction": action.direction, "function_number": action.function_number,
                "enabled": action.enabled}

    def recording_state(self) -> dict[str, Any]:
        """Expose recording status and immutable plans without transport details."""
        recorder = self.runtime.recording if self.runtime is not None else None
        active = {"train_id": recorder.train_id,
                  "actions": [self._recording_action_payload(action) for action in recorder.actions]}
        if recorder is None or not recorder.active:
            active = None
        return {"active": active, "history": [
            {"train_id": plan.train_id, "started_at": plan.started_at, "stopped_at": plan.stopped_at,
             "duration": plan.duration, "action_count": plan.action_count,
             "actions": [self._recording_action_payload(action) for action in plan.actions]}
            for plan in self._recording_history[-10:]
        ]}

    def automation_programs_state(self) -> list[dict[str, Any]]:
        """Expose authored automation programs without compiled runtime actions."""
        result = []
        for program in self._automation_programs:
            item = {key: deepcopy(value) for key, value in program.items() if key != "_compiled_actions"}
            item["train_id"] = self._ui_train_id(str(program.get("train_id", "")))
            result.append(item)
        return result

    def _compile_automation_program(self, train_id: str, blocks: Any) -> tuple[tuple[RecordedAction, ...], float]:
        """Compile UI block definitions into the existing validated playback model."""
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("an automation program needs at least one action block")
        canonical_id = self._canonical_train_id(str(train_id))
        train = next((item for item in self.trains if item.get("id") == canonical_id), None)
        if train is None:
            raise ValueError(f"Unknown train: {train_id}")
        maximum = max(1.0, float(train.get("maxSpeed", train.get("max_speed_kmh", 140)) or 140))
        actions: list[RecordedAction] = []
        cursor = 0.0

        def number(value: Any, field: str, minimum: float = 0.0) -> float:
            if isinstance(value, bool):
                raise ValueError(f"{field} must be a number")
            try:
                result = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be a number") from exc
            if not math.isfinite(result) or result < minimum:
                raise ValueError(f"{field} must be a finite number >= {minimum}")
            return result

        for index, raw in enumerate(blocks):
            if not isinstance(raw, dict):
                raise ValueError(f"automation block {index + 1} must be an object")
            kind = str(raw.get("type", raw.get("kind", ""))).strip().lower()
            if kind in {"drive", "speed"}:
                speed = number(raw.get("speed_kmh", raw.get("speed", 0)), "speed_kmh")
                duration = number(raw.get("duration_s", raw.get("duration", 0)), "duration_s")
                if speed > maximum:
                    raise ValueError(f"speed_kmh cannot exceed the train maximum of {maximum:g}")
                actions.append(RecordedAction(cursor, "speed", canonical_id, speed=speed / maximum))
                cursor += duration
                if duration > 0:
                    actions.append(RecordedAction(cursor, "speed", canonical_id, speed=0.0))
            elif kind == "wait":
                cursor += number(raw.get("duration_s", raw.get("duration", 1)), "duration_s")
            elif kind == "direction":
                direction = str(raw.get("direction", "forward")).strip().lower()
                if direction not in {"forward", "reverse"}:
                    raise ValueError("direction must be forward or reverse")
                actions.append(RecordedAction(cursor, "direction", canonical_id, direction=direction))
            elif kind in {"function", "lighting"}:
                raw_number = raw.get("function_number", raw.get("function", 0))
                if isinstance(raw_number, bool):
                    raise ValueError("function_number must be an integer")
                try:
                    function_number = int(raw_number)
                except (TypeError, ValueError) as exc:
                    raise ValueError("function_number must be an integer") from exc
                if function_number < 0 or function_number > 31:
                    raise ValueError("function_number must be between 0 and 31")
                enabled = raw.get("enabled", False)
                if not isinstance(enabled, bool):
                    enabled = str(enabled).strip().lower() in {"true", "on", "1", "yes"}
                actions.append(RecordedAction(cursor, "function", canonical_id, function_number=function_number, enabled=enabled))
            elif kind == "stop":
                actions.append(RecordedAction(cursor, "speed", canonical_id, speed=0.0))
            else:
                raise ValueError(f"unknown automation block type: {kind or 'blank'}")

        if not actions:
            raise ValueError("automation blocks do not contain a playable action")
        return tuple(actions), cursor

    def _automation_plan(self, program: dict[str, Any]) -> PlaybackPlan:
        train_id = self._canonical_train_id(str(program["train_id"]))
        actions = tuple(
            RecordedAction.from_mapping(action, train_id=train_id)
            for action in program.get("_compiled_actions", ())
        )
        duration = float(program.get("duration_s", 0) or 0)
        return PlaybackPlan(train_id, actions, 0.0, duration)

    def save_automation_program(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw = payload.get("program", payload)
        if not isinstance(raw, dict):
            raise ValueError("program must be an object")
        program_id = str(raw.get("id", "")).strip() or f"program-{int(time.time() * 1000)}"
        name = str(raw.get("name", "Untitled train routine")).strip() or "Untitled train routine"
        train_id = self._canonical_train_id(str(raw.get("train_id", "")))
        actions, duration = self._compile_automation_program(train_id, raw.get("blocks"))
        stored = {
            "id": program_id,
            "name": name,
            "train_id": train_id,
            "blocks": deepcopy(raw.get("blocks")),
            "duration_s": round(duration, 3),
            "_compiled_actions": [self._recording_action_payload(action) for action in actions],
        }
        self._automation_programs = [item for item in self._automation_programs if item.get("id") != program_id]
        self._automation_programs.append(stored)
        self.events.append({"type": "automation_program_saved", "program_id": program_id, "train_id": train_id})
        return self.automation_programs_state()

    def _record_action_if_active(self, action: dict[str, Any]) -> None:
        recorder = self.runtime.recording if self.runtime is not None else None
        if recorder is None or not recorder.active:
            return
        try:
            recorder.append(action, timestamp=time.time())
        except ValueError:
            # Recording is observational; a malformed or out-of-order action
            # must never invalidate the underlying train command.
            return

    def _playback_plan(self, plan: PlaybackPlan, payload: dict[str, Any], event_type: str) -> dict[str, Any]:
        """Play a recorded or authored plan and leave the train in a safe stopped state."""
        if self.runtime is None:
            raise ValueError("runtime is not available")
        if not self.track_power:
            raise ValueError("switch track power on before playing a recording")
        if not self.simulation_mode and payload.get("confirm") is not True:
            raise ValueError("real-track playback requires confirm=true")
        train_id = self._canonical_train_id(plan.train_id)
        train = next((item for item in self.trains if item.get("id") == train_id), None)
        if train is None:
            raise ValueError(f"Unknown train: {train_id}")
        control = self.runtime.dispatcher.register_train(train_id)
        is_automatic = control.mode is ControlMode.AUTOMATIC
        allow_automatic = payload.get("automatic") is True
        if is_automatic and not allow_automatic:
            raise ValueError("automatic-mode playback requires automatic=true")
        maximum = max(1.0, float(train.get("maxSpeed", train.get("max_speed_kmh", 140)) or 140))
        movement_attempted = False
        playback_started = time.monotonic()
        try:
            for action in plan.actions:
                target_delay = max(0.0, float(action.timestamp) - float(plan.started_at))
                remaining = target_delay - (time.monotonic() - playback_started)
                if remaining > 0:
                    time.sleep(remaining)
                if action.operation == "speed":
                    if float(action.speed) > 0:
                        movement_attempted = True
                    command = self.runtime.dispatcher.automatic_speed if is_automatic else self.runtime.dispatcher.manual_speed
                    result = command(train_id, float(action.speed))
                elif action.operation == "direction":
                    result = self.runtime.track.set_train_direction(train_id, forward=action.direction == "forward")
                    if hasattr(result, "accepted") and result.accepted:
                        train["direction"] = action.direction
                else:
                    if not hasattr(self.runtime.track, "set_train_function"):
                        raise ValueError("the active track adapter does not support decoder functions")
                    result = self.runtime.track.set_train_function(train_id, int(action.function_number), enabled=bool(action.enabled))
                    train.setdefault("decoder_function_states", {})[str(action.function_number)] = bool(action.enabled)
                if hasattr(result, "accepted") and not result.accepted:
                    raise ValueError(result.detail or "recorded action was rejected")
                if action.operation == "speed":
                    train["speed"] = round(float(action.speed) * maximum)
                    train["requested_speed_kmh"] = train["speed"]
            self.events.append({"type": event_type, "train_id": train_id, "action_count": plan.action_count})
            return self.recording_state()
        finally:
            if movement_attempted:
                self.runtime.track.stop_train(train_id)
            control.manual_speed = control.automatic_speed = 0.0
            train["speed"] = train["requested_speed_kmh"] = 0

    def play_recording(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Play one stored recording and leave the train in a safe stopped state."""
        if not self._recording_history:
            raise ValueError("no recording is available")
        index = int(payload.get("index", len(self._recording_history) - 1))
        if index < 0 or index >= len(self._recording_history):
            raise ValueError("recording index is out of range")
        return self._playback_plan(self._recording_history[index], payload, "recording_played")

    def play_automation_program(self, payload: dict[str, Any]) -> dict[str, Any]:
        program_id = str(payload.get("program_id", "")).strip()
        program = next((item for item in self._automation_programs if item.get("id") == program_id), None)
        if program is None:
            raise ValueError("automation program not found")
        return self._playback_plan(self._automation_plan(program), payload, "automation_program_played")

    def request_decoder_programming(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate a programming request without issuing an unsupported CV write."""
        train_id = self._canonical_train_id(str(payload.get("train_id", "")))
        train = next((item for item in self.trains if item.get("id") == train_id), None)
        if train is None:
            raise ValueError(f"Unknown train: {train_id}")
        target = str(payload.get("target", "main")).strip().lower()
        if target not in {"main", "programming_track"}:
            raise ValueError("target must be main or programming_track")
        address_value = payload.get("address", train.get("address", train.get("number")))
        try:
            address = int(address_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("DCC address must be an integer") from exc
        if address < 1 or address > 9999:
            raise ValueError("DCC address must be between 1 and 9999")
        try:
            cv = int(payload.get("cv"))
            value = int(payload.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValueError("CV and value must be integers") from exc
        if cv < 1 or cv > 1024:
            raise ValueError("CV must be between 1 and 1024")
        if value < 0 or value > 255:
            raise ValueError("CV value must be between 0 and 255")
        request = {
            "train_id": train_id,
            "address": address,
            "cv": cv,
            "value": value,
            "target": target,
            "operation": "write",
            "status": "validated",
        }
        self._programming_state["last_request"] = request
        self.events.append({"type": "decoder_programming_validated", "request": request})
        return self.programming_state()

    def execute_decoder_programming(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute an explicitly confirmed CV write on a real Z21 track."""

        self.request_decoder_programming(payload)
        request = self._programming_state["last_request"]
        if self.simulation_mode:
            request["status"] = "simulation_only"
            self._programming_state["detail"] = "Simulation accepted the request without sending a decoder write."
            return self.programming_state()
        if self.runtime is None or not hasattr(self.runtime.track, "write_cv"):
            raise ValueError("the active track adapter does not support CV programming")
        if request["target"] == "main" and not self.track_power:
            raise ValueError("switch track power on before programming on the main")
        result = self.runtime.track.write_cv(request["train_id"], request["cv"], request["value"], target=request["target"])
        if not result.accepted:
            request["status"] = "rejected"
            raise ValueError(result.detail or "Z21 rejected the CV programming request")
        request["status"] = "sent"
        self._programming_state["supported"] = True
        self._programming_state["detail"] = result.detail or "Z21 accepted the CV programming request."
        self.events.append({"type": "decoder_programmed", "request": deepcopy(request), "detail": result.detail})
        return self.programming_state()

    def request_dcc_address_programming(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate a requested decoder-address change without touching hardware."""

        train_id = self._canonical_train_id(str(payload.get("train_id", "")))
        train = next((item for item in self.trains if item.get("id") == train_id), None)
        if train is None:
            raise ValueError(f"Unknown train: {train_id}")
        target = str(payload.get("target", "main")).strip().lower()
        if target not in {"main", "programming_track"}:
            raise ValueError("target must be main or programming_track")
        try:
            current_address = int(payload.get("address", train.get("address", train.get("number"))))
            new_address = int(payload.get("new_address", payload.get("address")))
        except (TypeError, ValueError) as exc:
            raise ValueError("current and new DCC addresses must be integers") from exc
        if not 1 <= current_address <= 9999 or not 1 <= new_address <= 9999:
            raise ValueError("DCC addresses must be between 1 and 9999")
        actual_address = train.get("address", train.get("number"))
        if actual_address not in (None, "") and int(actual_address) != current_address:
            raise ValueError(f"current DCC address does not match the saved address ({int(actual_address)})")
        collision = next((item for item in self.trains if item.get("id") != train_id and str(item.get("address", "")) == str(new_address)), None)
        if collision is not None:
            raise ValueError(f"DCC address {new_address} is already assigned to {collision.get('name', collision.get('id'))}")
        request = {
            "train_id": train_id,
            "address": current_address,
            "new_address": new_address,
            "target": target,
            "operation": "address",
            "status": "validated",
        }
        self._programming_state["last_address_request"] = request
        self.events.append({"type": "dcc_address_programming_validated", "request": deepcopy(request)})
        return self.programming_state()

    def execute_dcc_address_programming(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Program and persist a decoder address after explicit confirmation."""

        self.request_dcc_address_programming(payload)
        request = self._programming_state["last_address_request"]
        train = next(item for item in self.trains if item.get("id") == request["train_id"])
        if self.simulation_mode:
            train["address"] = request["new_address"]
            request["status"] = "simulation_only"
            self._sync_train_database()
            self._programming_state["supported"] = True
            self._programming_state["detail"] = "Simulation updated the saved decoder address without sending a hardware write."
            self.events.append({"type": "dcc_address_programmed", "request": deepcopy(request), "detail": self._programming_state["detail"]})
            return self.programming_state()
        if request["target"] == "main" and not self.track_power:
            raise ValueError("switch track power on before programming on the main")
        if self.runtime is None or not hasattr(self.runtime.track, "program_dcc_address"):
            raise ValueError("the active track adapter does not support DCC address programming")
        result = self.runtime.track.program_dcc_address(train["id"], request["new_address"], target=request["target"])
        if not result.accepted:
            request["status"] = "rejected"
            raise ValueError(result.detail or "Z21 rejected the DCC address programming request")
        train["address"] = request["new_address"]
        request["status"] = "sent"
        self._sync_train_database()
        self._programming_state["supported"] = True
        self._programming_state["detail"] = result.detail or "Z21 accepted the DCC address programming request."
        self.events.append({"type": "dcc_address_programmed", "request": deepcopy(request), "detail": self._programming_state["detail"]})
        return self.programming_state()

    def read_decoder_cv(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Read a CV from a real Z21 decoder when the selected mode supports it."""

        state = self.request_decoder_programming(payload)
        request = state["last_request"]
        if self.simulation_mode:
            self._programming_state["last_read"] = {**request, "status": "simulation_only", "value": None}
            return self.programming_state()
        if self.runtime is None or not hasattr(self.runtime.track, "read_cv"):
            raise ValueError("the active track adapter does not support CV reading")
        if request["target"] == "main" and not self.track_power:
            raise ValueError("switch track power on before reading on the main")
        result, value = self.runtime.track.read_cv(request["train_id"], request["cv"], target=request["target"])
        if not result.accepted:
            raise ValueError(result.detail or "Z21 rejected the CV read request")
        self._programming_state["last_read"] = {**request, "status": "read", "value": value}
        self._programming_state["supported"] = True
        self._programming_state["detail"] = result.detail or "CV read completed."
        self.events.append({"type": "decoder_cv_read", "request": deepcopy(self._programming_state["last_read"])})
        return self.programming_state()

    def scan_train_presence(self) -> dict[str, Any]:
        """Synchronously scan saved addresses for direct callers and tests."""

        if self.runtime is None:
            raise ValueError("runtime is not available")
        with self._lock:
            saved_trains = deepcopy(self.trains)
            reported = {motion.train_id for motion in self.runtime.track.get_snapshot().trains}
            track = self.runtime.track
            simulation_mode = self.simulation_mode
        result = self._scan_presence_records(saved_trains, reported, track=track, simulation_mode=simulation_mode)
        with self._lock:
            self._presence_state = {
                **result,
                "running": False,
                "started_at": self._presence_state.get("started_at"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
            return deepcopy(self._presence_state)

    def _scan_presence_records(
        self,
        saved_trains: list[dict[str, Any]],
        reported: set[str],
        *,
        track: Any,
        simulation_mode: bool,
    ) -> dict[str, Any]:
        """Scan an immutable caller snapshot without acquiring the app lock."""

        addresses = {int(train.get("address")): train["id"] for train in saved_trains if str(train.get("address", "")).isdigit()}
        if not simulation_mode and hasattr(track, "probe_train_address"):
            def probe(address: int) -> dict[str, Any]:
                result = track.probe_train_address(address)
                railcom_detected = bool(result.accepted and result.command == "probe_railcom")
                station_known = bool(result.accepted and result.command == "probe_loco_info")
                source = "Z21 RailCom" if railcom_detected else "Z21 locomotive info"
                return {
                    "detected": railcom_detected,
                    "known_to_station": station_known,
                    "source": source,
                    "detail": result.detail,
                }
        else:
            def probe(address: int) -> dict[str, Any]:
                return {"detected": addresses.get(int(address)) in reported, "source": "reported track feedback"}
        detector = SavedTrainPresenceService(probe)
        return detector.scan(saved_trains).as_dict()

    def _start_presence_scan(self) -> dict[str, Any]:
        """Start a non-blocking presence scan from a lock-protected snapshot."""

        if self.runtime is None:
            raise ValueError("runtime is not available")
        if self._presence_thread is not None and self._presence_thread.is_alive():
            return deepcopy(self._presence_state)
        saved_trains = deepcopy(self.trains)
        reported = {motion.train_id for motion in self.runtime.track.get_snapshot().trains}
        track = self.runtime.track
        simulation_mode = self.simulation_mode
        started_at = datetime.now(timezone.utc).isoformat()
        self._presence_state = {
            **self._presence_state,
            "running": True,
            "started_at": started_at,
            "completed_at": None,
            "error": None,
        }

        def worker() -> None:
            try:
                result = self._scan_presence_records(saved_trains, reported, track=track, simulation_mode=simulation_mode)
                error = None
            except Exception as exc:  # Keep one hardware scan from killing the controller worker.
                result = {"results": [], "summary": {"total": 0, "detected": 0, "unknown": 0, "errors": 1}}
                error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._presence_state = {
                    **result,
                    "running": False,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": error,
                }
                self.events.append({"type": "train_presence_scan", "summary": self._presence_state["summary"], "error": error})
                self._presence_thread = None

        self._presence_thread = threading.Thread(target=worker, name="h0-train-presence", daemon=True)
        self._presence_thread.start()
        return deepcopy(self._presence_state)

    def _validate_schedule_coordinate(self, schedule: dict[str, Any]) -> None:
        raw = schedule.get("destination_coordinate")
        if not raw:
            return
        if not isinstance(raw, dict):
            raise ValueError("destination_coordinate must contain x and y")
        try:
            x, y = float(raw.get("x")), float(raw.get("y"))
        except (TypeError, ValueError) as exc:
            raise ValueError("destination_coordinate must contain numeric x and y") from exc
        coordinate = nearest_track_coordinate(self.blocks, self._topology_edges(), x, y)
        if coordinate is None:
            raise ValueError("destination coordinate is not on the configured track")
        schedule["destination_coordinate"] = {
            "x": round(coordinate.x, 2), "y": round(coordinate.y, 2),
            "from_node": coordinate.from_node.lower(), "to_node": coordinate.to_node.lower(),
            "progress": round(coordinate.progress, 6),
        }

    def _validate_schedule_dispatch(self, schedule: dict[str, Any]) -> None:
        """Normalize a timetable's dispatch target and validate saved routes."""

        route_id = str(schedule.get("route_id", "") or "").strip()
        raw_mode = str(schedule.get("dispatch_mode", "") or "").strip().lower()
        if not raw_mode:
            raw_mode = "route" if route_id else "coordinate" if schedule.get("destination_coordinate") else "display"
        if raw_mode not in {"route", "coordinate", "display"}:
            raise ValueError("dispatch_mode must be route, coordinate, or display")
        if raw_mode == "route":
            if not route_id:
                raise ValueError("route dispatch requires a route_id")
            route = next((item for item in self.routes if str(item.get("id", "")) == route_id), None)
            if route is None:
                raise ValueError(f"Unknown route: {route_id}")
            schedule["route_id"] = route_id
            schedule["destination_coordinate"] = None
        elif raw_mode == "coordinate":
            if not schedule.get("destination_coordinate"):
                raise ValueError("coordinate dispatch requires destination_coordinate")
            schedule["route_id"] = None
        else:
            schedule["route_id"] = None
            schedule["destination_coordinate"] = None
        schedule["dispatch_mode"] = raw_mode

    def _schedule_route_target(self, schedule: dict[str, Any], stop_id: str, train_id: str) -> dict[str, Any] | None:
        """Bind a saved route to the assigned train when a service departs."""

        route_id = str(schedule.get("route_id", "") or "").strip()
        if not route_id:
            return None
        if self.runtime is None:
            raise ValueError("controller runtime unavailable")
        route = next((item for item in self.routes if str(item.get("id", "")) == route_id), None)
        if route is None:
            raise ValueError(f"Unknown route: {route_id}")
        if not route.get("enabled", True):
            raise ValueError(f"cannot dispatch disabled route: {route_id}")
        canonical_train_id = self._canonical_train_id(train_id)
        train = next((item for item in self.trains if str(item.get("id")) == canonical_train_id), None)
        if train is None:
            raise ValueError(f"Unknown train: {train_id}")
        path = tuple(str(item).upper() for item in route.get("node_ids", ()) if str(item).strip())
        train["scheduled_route_id"] = route_id
        train["scheduled_route_name"] = str(route.get("name", route_id))
        if path:
            self.runtime.route_updater.set_route(canonical_train_id, path)
            if hasattr(self.runtime.track, "set_train_route"):
                result = self.runtime.track.set_train_route(canonical_train_id, path)
                if hasattr(result, "accepted") and not result.accepted:
                    raise ValueError(result.detail or "scheduled route was rejected")
            train["destination_block_id"] = path[-1]
            train["route"] = list(path)
            self._publish_domain_event(RouteChanged(train_id=canonical_train_id, route=path))
        target = {
            "route_id": route_id,
            "name": str(route.get("name", route_id)),
            "node_ids": [item.lower() for item in path],
            "flow": deepcopy(route.get("flow", [])),
            "schedule_id": str(schedule.get("id", "")),
        }
        self.events.append({
            "type": "schedule_route_bound", "schedule_id": str(schedule.get("id", "")),
            "stop_id": str(stop_id), "train_id": canonical_train_id, "route": deepcopy(target),
        })
        return target

    def _schedule_coordinate_target(self, schedule: dict[str, Any], stop_id: str, train_id: str) -> dict[str, Any] | None:
        """Plan a calibrated destination for a timetable departure.

        A timetable may contain one destination coordinate for the whole service
        or a coordinate on an individual multi-stop entry. This method only
        plans and applies the route target; physical movement remains governed by
        the dispatcher and the train's current control mode.
        """

        raw: Any = schedule.get("destination_coordinate")
        suffix = str(stop_id).split("#", 1)[1] if "#" in str(stop_id) else ""
        stops = schedule.get("stops")
        if suffix.isdigit() and isinstance(stops, (list, tuple)):
            index = int(suffix)
            if 0 <= index < len(stops) and isinstance(stops[index], dict):
                raw = stops[index].get("destination_coordinate", raw)
        if not raw:
            return None
        if self.runtime is None:
            raise ValueError("controller runtime unavailable")
        train_id = self._canonical_train_id(train_id)
        train = next((item for item in self.trains if str(item.get("id")) == train_id), None)
        if train is None:
            raise ValueError(f"Unknown train: {train_id}")
        if not isinstance(raw, dict):
            raise ValueError("destination_coordinate must contain x and y")
        try:
            x, y = float(raw.get("x")), float(raw.get("y"))
        except (TypeError, ValueError) as exc:
            raise ValueError("destination_coordinate must contain numeric x and y") from exc
        calibration = self.runtime.calibration.history(train_id)
        if not calibration:
            raise ValueError(f"train {train_id} needs a calibration measurement before schedule movement")
        motion = next((item for item in self.runtime.track.get_snapshot().trains if item.train_id == train_id), None)
        current = str((motion.block_id if motion else train.get("block_id", "")) or "").strip().upper()
        direction = "forward" if self.runtime.track.get_train_direction(train_id) else "reverse"
        try:
            planner_blocks = [{**block, "id": str(block.get("id", "")).strip().upper()} for block in self.blocks]
            planner_edges = [{**edge, "from": str(edge.get("from", "")).strip().upper(), "to": str(edge.get("to", "")).strip().upper()} for edge in self._topology_edges()]
            plan = CoordinateMovementPlanner(planner_blocks, planner_edges, calibration).plan(
                train_id, x, y, speed_kmh=10, direction=direction,
                occupied_blocks=self.runtime.track.get_snapshot().occupied_blocks,
            )
        except MovementPlanValidationError as exc:
            raise ValueError(str(exc)) from exc
        if current and current != plan.source_block_id:
            raise ValueError("scheduled destination must be ahead of the train in its current direction")
        target = {
            "x": round(plan.x, 2), "y": round(plan.y, 2),
            "from_node": plan.source_block_id.lower(), "to_node": plan.target_block_id.lower(),
            "progress": round(plan.progress, 6), "distance_mm": round(plan.distance_mm, 2),
            "estimated_duration_ms": plan.estimated_duration_ms, "direction": plan.direction,
            "speed_kmh": plan.speed_kmh, "schedule_id": str(schedule.get("id", "")),
        }
        train["target_coordinate"] = target
        train["route"] = [plan.source_block_id.lower(), plan.target_block_id.lower()]
        self.runtime.route_updater.set_route(train_id, (plan.source_block_id, plan.target_block_id))
        if hasattr(self.runtime.track, "set_train_route"):
            result = self.runtime.track.set_train_route(train_id, (plan.source_block_id, plan.target_block_id))
            if hasattr(result, "accepted") and not result.accepted:
                raise ValueError(result.detail or "scheduled coordinate route was rejected")
        if hasattr(self.runtime.track, "set_train_coordinate_target"):
            result = self.runtime.track.set_train_coordinate_target(train_id, plan.progress)
            if hasattr(result, "accepted") and not result.accepted:
                raise ValueError(result.detail or "scheduled coordinate target was rejected")
        mode = str(train.get("mode", "manual")).lower()
        if mode == ControlMode.AUTOMATIC.value:
            maximum = max(1.0, float(train.get("maxSpeed", train.get("max_speed_kmh", 140))))
            speed = max(0.0, min(1.0, float(train.get("requested_speed_kmh", train.get("speed", 10)) or 10) / maximum))
            if self.simulation_mode:
                result = self.runtime.dispatcher.automatic_speed(train_id, speed)
                if hasattr(result, "accepted") and not result.accepted:
                    raise ValueError(result.detail or "scheduled automatic movement was rejected")
            else:
                if not self.track_power:
                    raise ValueError("switch track power on before scheduled coordinate movement")
                try:
                    execution = CoordinateMovementExecutionPlanner(max_duration_ms=120000).build(plan, calibration)
                    status = self.runtime.coordinate_movement.start(execution, confirmed=True, allow_automatic=True)
                except (ValueError, MovementPlanValidationError) as exc:
                    raise ValueError(str(exc)) from exc
                self._coordinate_execution_state = status.as_dict()
                self.events.append({
                    "type": "schedule_coordinate_execution_started", "schedule_id": str(schedule.get("id", "")),
                    "stop_id": str(stop_id), "train_id": train_id, "duration_ms": execution.duration_ms,
                })
        self.events.append({
            "type": "schedule_coordinate_targeted", "schedule_id": str(schedule.get("id", "")),
            "stop_id": str(stop_id), "train_id": train_id, "coordinate": deepcopy(target),
            "mode": mode,
        })
        return target

    def train_catalogue(self, format_name: str = "json") -> dict[str, Any]:
        """Return a portable export of all persisted train model details."""

        if self.runtime is None:
            records: list[Any] = []
        else:
            records = list(self.runtime.train_database.list())
            records = [self.runtime.train_database.get_full_train(record.train_id) for record in records]
        catalogue = TrainCatalogue(record for record in records if record is not None)
        normalized = str(format_name or "json").strip().lower()
        if normalized == "csv":
            return {"format": "csv", "content": export_csv(catalogue)}
        if normalized != "json":
            raise ValueError("catalogue format must be json or csv")
        return json.loads(export_json(catalogue))

    def import_train_catalogue(
        self,
        content: Any,
        *,
        format_name: str = "json",
        on_conflict: str = "error",
    ) -> dict[str, Any]:
        """Validate and merge a portable catalogue into the live model store."""

        if self.runtime is None:
            raise RuntimeError("runtime is not available")
        normalized = str(format_name or "json").strip().lower()
        if normalized == "json":
            source = content if isinstance(content, str) else json.dumps(content)
            records = import_json(source)
        elif normalized == "csv":
            source = content if isinstance(content, str) else str(content or "")
            records = import_csv(source)
        else:
            raise ValueError("catalogue format must be json or csv")
        catalogue = TrainCatalogue(records)
        merged = catalogue.merge_into(self.runtime.train_database, on_conflict=on_conflict)
        affected = set(merged.imported_ids) | set(merged.updated_ids)
        for record in catalogue:
            if record.train_id not in affected:
                continue
            model = record.train
            row = next((item for item in self.trains if str(item.get("id")) == model.train_id), None)
            if row is None:
                row = {
                    "id": model.train_id,
                    "mode": ControlMode.STOPPED.value,
                    "speed": 0,
                    "direction": "forward",
                    "block_id": str(self.blocks[0].get("id", "B01")) if self.blocks else "B01",
                }
                self.trains.append(row)
            row.update({
                "name": model.name,
                "address": model.decoder_address,
                "decoder_protocol": model.decoder_protocol,
                "manufacturer": model.manufacturer,
                "model_number": model.model,
                "era": model.era,
                "length_mm": model.length_mm,
                "length": model.length_mm if model.length_mm is not None else row.get("length", ""),
                "mass_g": model.mass_g,
                "maxSpeed": model.max_speed_kmh if model.max_speed_kmh is not None else row.get("maxSpeed", 140),
                "decoder_functions": [
                    {
                        "function_number": item.function_number,
                        "name": item.name,
                        "description": item.description,
                        "momentary": item.momentary,
                        "enabled": item.enabled,
                    }
                    for item in record.decoder_functions
                ],
                "maintenance_records": [
                    {
                        "record_id": item.record_id,
                        "service_date": item.service_date,
                        "service_type": item.service_type,
                        "description": item.description,
                        "mileage_km": item.mileage_km,
                        "cost": item.cost,
                        "performed_by": item.performed_by,
                        "next_service_date": item.next_service_date,
                    }
                    for item in record.maintenance_records
                ],
                "consist": [
                    {
                        "id": item.rolling_stock_id,
                        "type": item.vehicle_type,
                        "name": item.name,
                        "manufacturer": item.manufacturer,
                        "model": item.model,
                        "length_mm": item.length_mm,
                        "mass_g": item.mass_g,
                    }
                    for item in record.rolling_stock
                ],
            })
            self._publish_domain_event(TrainDatabaseChanged(train_id=model.train_id, entity="catalogue", action="imported" if model.train_id in merged.imported_ids else "updated", record_id=model.train_id))
        self._sync_runtime_from_ui()
        self.events.append({
            "type": "train_catalogue_imported",
            "format": normalized,
            "imported": list(merged.imported_ids),
            "updated": list(merged.updated_ids),
            "skipped": list(merged.skipped_ids),
        })
        return {
            "imported": list(merged.imported_ids),
            "updated": list(merged.updated_ids),
            "skipped": list(merged.skipped_ids),
        }

    def _sync_ui_from_runtime(self) -> None:
        if self.runtime is None:
            return
        track_snapshot = self.runtime.track.get_snapshot()
        self.feedback_occupancy = {str(block_id): tuple(values) for block_id, values in track_snapshot.occupied_blocks.items()}
        motions = {motion.train_id: motion for motion in track_snapshot.trains}
        previous_blocks = getattr(self, "_last_train_blocks", {})
        current_blocks: dict[str, str] = {}
        for train in self.trains:
            train_id = str(train["id"])
            motion = motions.get(train_id)
            if motion is not None:
                current_blocks[train_id] = str(motion.block_id)
                if previous_blocks.get(train_id) not in (None, str(motion.block_id)):
                    self._publish_domain_event(
                        TrainPositionChanged(
                            train_id=train_id,
                            from_block_id=previous_blocks.get(train_id),
                            to_block_id=str(motion.block_id),
                        )
                    )
                train["block_id"] = motion.block_id
                train["speed"] = round(float(motion.target_speed) * float(train.get("maxSpeed", train.get("max_speed_kmh", 140))))
                control = self.runtime.dispatcher.trains.get(train_id)
                train["requested_speed_kmh"] = (control.desired_speed if control else 0) * float(train.get("maxSpeed", train.get("max_speed_kmh", 140)))
                if previous_blocks.get(train_id) is None:
                    current_blocks[train_id] = str(motion.block_id)
        self._last_train_blocks = current_blocks

    def _snapshot(self) -> dict[str, Any]:
        connection = self.runtime.track.connection_status() if self.runtime is not None and self.z21_host else self.runtime.connection.status if self.runtime is not None else None
        connected = bool(connection.connected) if connection is not None else self.connected
        feedback_healthy = getattr(self.runtime.track, "feedback_healthy", True) if self.runtime is not None else True
        feedback_error = getattr(self.runtime.track, "feedback_error", "") if self.runtime is not None else ""
        return {
            "simulation_mode": self.simulation_mode,
            "connected": connected,
            "connection": {
                "mode": "simulation" if self.simulation_mode else "z21",
                "connected": connected,
                "endpoint": connection.endpoint if connection is not None and connection.endpoint else "127.0.0.1:21105",
                "detail": connection.detail if connection is not None else "",
            },
            "tick": self.tick_count,
            "track_power": self.track_power,
            "trains": self.trains,
            "blocks": self.blocks,
            "turnouts": self.turnouts,
            "stations": self.stations,
            "signals": self.signals,
            "waypoints": self.waypoints,
            "turntables": self.turntables,
            "platforms": self.platforms,
            "feedback": {"healthy": feedback_healthy, "error": feedback_error, "mapped_contacts": len(self.feedback_map)},
            "events": self.events[-25:],
        }

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._ui_snapshot()

    def raw_state(self) -> dict[str, Any]:
        """Return the backend-oriented snapshot for diagnostics and tests."""

        with self._lock:
            return self._snapshot()

    def layout_info(self) -> dict[str, Any]:
        """Controller positions, occupancy and executing operations, not catalogue totals."""
        block_ids = {str(block["id"]).upper() for block in self.blocks}
        trains = [
            train for train in self.trains
            if train.get("graph_enabled", True)
            and str(train.get("block_id", "")).upper() in block_ids
        ]
        if not self.simulation_mode:
            reported = {motion.train_id for motion in self.runtime.track.get_snapshot().trains}
            trains = [train for train in trains if train["id"] in reported]
        controls = self.runtime.dispatcher.trains if self.runtime else {}
        routes = self.runtime.route_updater.desired_routes if self.runtime else {}
        active = [train for train in trains
                  if self.track_power and (not self.simulation_mode or self.simulation_running)
                  and (control := controls.get(str(train["id"]))) is not None
                  and control.mode is ControlMode.AUTOMATIC and control.desired_speed > 0
                  and len(route := routes.get(str(train["id"]), ())) > 1
                  and str(train.get("block_id", "")).upper() != route[-1]]
        telemetry = dict(getattr(self, "_power_telemetry", {"available": False, "reason":
            "Not measured in simulation" if self.simulation_mode else "Waiting for Z21 readings"}))
        if not self.simulation_mode and time.monotonic() - getattr(self, "_power_read_at", 0) > 15:
            telemetry = {"available": False, "reason": "No fresh Z21 power readings"}
        return {"block_count": len(block_ids),
                "occupied_blocks": sum(block["status"] == "occupied" for block in self._ui_blocks()),
                "train_count": len(trains),
                "manual_trains": sum(str(t.get("mode", "")).lower() == "manual" for t in trains),
                "automatic_trains": sum(str(t.get("mode", "")).lower() == "automatic" for t in trains),
                "stopped_trains": sum(str(t.get("mode", "")).lower() not in {"manual", "automatic"} for t in trains),
                "active_routes": len(active), "power": telemetry,
                "trains": [{"id": t["id"], "name": t.get("name", t["id"]),
                            "block_id": t["block_id"], "mode": t.get("mode", "stopped")} for t in trains]}

    def check_connection(self) -> None:
        # Serialize all UDP request/response traffic with commands and state updates.
        with self._lock:
            if self.runtime is None:
                return
            connection = self.runtime.connection.check()
            if self.z21_host and connection.status.connected:
                if time.monotonic() - getattr(self, "_power_read_at", 0) >= 5:
                    self._power_telemetry = self.runtime.track.read_power_telemetry()
                    self._power_read_at = time.monotonic()
            if self.z21_host and not self.runtime.track.connection_status().connected:
                self._power_telemetry = {"available": False, "reason": "Z21 disconnected"}
                self.runtime.dispatcher.emergency_stop()
                self.track_power = False
                for train in self.trains:
                    train["mode"] = ControlMode.STOPPED.value
                    train["speed"] = 0
                self._sync_ui_from_runtime()

    def _ui_snapshot(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        elapsed_seconds = int(self.runtime.track.get_snapshot().time_seconds)
        world_elapsed_seconds = int(self._world_clock_seconds) % 86400
        world_hours = world_elapsed_seconds // 3600
        world_minutes = (world_elapsed_seconds % 3600) // 60
        world_clock = f"{world_hours:02d}:{world_minutes:02d}"
        return {
            "simulation_mode": snapshot["simulation_mode"],
            "mode": "simulation" if self.simulation_mode else "manual",
            "connection": {
                "connected": snapshot["connected"],
                "simulated": snapshot["simulation_mode"],
                "mode": snapshot["connection"]["mode"],
                "endpoint": snapshot["connection"]["endpoint"],
                "label": "Simulation fallback" if snapshot["simulation_mode"] else "Z21 connected" if snapshot["connected"] else "Z21 disconnected",
                "detail": "Local sample state" if snapshot["simulation_mode"] else snapshot["connection"]["detail"],
            },
            "simulation": {
                "running": self.simulation_running,
                "rate": 1,
                "clock": f"{(elapsed_seconds // 3600) % 24:02d}:{(elapsed_seconds // 60) % 60:02d}:{elapsed_seconds % 60:02d}",
                "elapsed_seconds": self.runtime.track.get_snapshot().time_seconds,
                "schedule_minutes": self.runtime.scheduler.world_current_tick,
                "world_clock": world_clock,
                "world_clock_seconds": self._world_clock_seconds,
                "date": "Simulation",
            },
            "tick": snapshot["tick"],
            "track_power": snapshot["track_power"],
            "motion_clock": {"running": bool(self._motion_thread and self._motion_thread.is_alive()),
                             "interval_seconds": self.runtime.track.tick_seconds if self.simulation_mode else 1.0},
            "layout_info": self.layout_info(),
            "calibration": self.calibration_state(),
            "presence": self.train_presence_state(),
            "rollingStockInventory": self.rolling_stock_inventory(),
            "programming": self.programming_state(),
            "recording": self.recording_state(),
            "automationPrograms": self.automation_programs_state(),
            "coordinate_execution": self.runtime.coordinate_movement.status.as_dict() if self.runtime is not None and self.runtime.coordinate_movement.status is not None else None,
            "feedback": snapshot["feedback"],
            "layout": {
                "name": self.layout_name,
                "blocks": self._ui_blocks(),
                "edges": self._ui_edges(),
                "connection_limits": self._ui_connection_limits(),
                "connections": self._ui_connections(),
                "turnouts": self._ui_turnouts(),
                "stations": list(self.stations),
                "signals": list(self.signals),
                "waypoints": list(self.waypoints),
                "turntables": list(self.turntables),
                "routes": deepcopy(self.routes),
                "platforms": list(self.platforms) or [
                    {"id": "p1", "name": "Central station", "blockIds": ["b01", "b02"]},
                    {"id": "p2", "name": "East platform", "blockIds": ["b03"]},
                    {"id": "p3", "name": "Yard", "blockIds": ["b04"]},
                ],
            },
            "trains": self._ui_trains(),
            "trainDatabase": self.train_database(),
            "schedules": list(self.schedules),
            "routes": deepcopy(self.routes),
            "blocks": self._ui_blocks(),
            "turnouts": self._ui_turnouts(),
            "events": snapshot["events"],
            "scans": list(self.scans),
            "settings": deepcopy(self._settings),
            "runtime": self.settings_payload()["runtime"],
        }

    def _ui_blocks(self) -> list[dict[str, Any]]:
        positions = {"B01": (62, 62), "B02": (222, 62), "B03": (382, 62), "B04": (542, 62)}
        reservations = getattr(self.runtime.route_updater, "reservations", {}) if self.runtime is not None else {}
        result = []
        for block in self.blocks:
            block_id = str(block["id"])
            occupants = [
                train["id"] for train in self.trains
                if train.get("graph_enabled", True) and train.get("block_id") == block_id
            ]
            if not self.simulation_mode:
                occupants = [motion.train_id for motion in self.runtime.track.get_snapshot().trains if motion.block_id == block_id]
            feedback_occupants = list(self.feedback_occupancy.get(block_id, ()))
            reservation_owner = reservations.get(block_id) or reservations.get(block_id.upper())
            default_x, default_y = positions.get(block_id, (62, 224))
            x, y = block.get("x", default_x), block.get("y", default_y)
            display_name = str(block.get("name", block_id) or block_id)
            result.append({
                "id": block_id.lower(), "name": display_name, "length_mm": block.get("length_mm", 0), "x": x, "y": y, "width": 126, "height": 56,
                "status": "occupied" if occupants or feedback_occupants else "route" if reservation_owner else "free", "trainId": self._ui_train_id(occupants[0]) if occupants else None,
                "reservedFor": self._ui_train_id(reservation_owner) if reservation_owner else None,
                "feedback": feedback_occupants,
                "neighborIds": [str(item).lower() for item in block.get("neighbor_ids", block.get("neighborIds", ()))],
                "station": block.get("station", display_name),
            })
        return result

    def _ui_edges(self) -> list[dict[str, Any]]:
        links = set((edge["from"], edge["to"]) for edge in self._topology_edges())
        for turnout in self.turnouts:
            entry = str(turnout.get("from", "")).lower()
            straight = str(turnout.get("to", "")).lower()
            diverging = str(turnout.get("alternate", "")).lower()
            if entry and straight:
                links.add((entry, straight))
            if entry and diverging:
                links.add((entry, diverging))
        return [self._edge_with_geometry(left, right) for left, right in sorted(links)]

    def _edge_with_geometry(self, left: str, right: str, *, status: str = "free") -> dict[str, Any]:
        edge = {"from": left, "to": right, "status": status}
        connected = {str(left).upper(), str(right).upper()}
        control_points: list[dict[str, float]] = []
        for waypoint in sorted(self.waypoints, key=lambda item: str(item.get("id", ""))):
            nodes = {str(value).upper() for value in waypoint.get("connected_node_ids", waypoint.get("connectedNodeIds", ())) }
            if not connected.issubset(nodes):
                continue
            try:
                point = {"x": float(waypoint.get("x", 0)), "y": float(waypoint.get("y", 0))}
            except (TypeError, ValueError):
                continue
            if math.isfinite(point["x"]) and math.isfinite(point["y"]):
                control_points.append(point)
        if control_points:
            edge["control_points"] = control_points
        return edge

    def _ui_connection_limits(self) -> list[dict[str, Any]]:
        return [{"from": row["from"].lower(), "to": row["to"].lower(),
                 "speed_limit_kmh": row.get("speed_limit_kmh"),
                 "train_speed_limits": {self._ui_train_id(key): value for key, value in row.get("train_speed_limits", {}).items()}}
                for row in self.connection_limits]

    def _ui_connections(self) -> list[dict[str, Any]]:
        rules = {(r["from"], r["to"]): r for r in self._ui_connection_limits()}
        pairs = {(e["from"], e["to"]) for e in self._ui_edges()}
        pairs |= {(right, left) for left, right in pairs}
        return [{"from": left, "to": right, "speed_limit_kmh": None, "train_speed_limits": {},
                 **rules.get((left, right), {})} for left, right in sorted(pairs)]

    def _train_motion_state(self, train: dict[str, Any]) -> dict[str, Any]:
        train_id = str(train["id"])
        motion = next((m for m in self.runtime.track.get_snapshot().trains if m.train_id == train_id), None)
        control = self.runtime.dispatcher.trains.get(train_id)
        maximum = float(train.get("maxSpeed", train.get("max_speed_kmh", 140)) or 140)
        requested = control.desired_speed if control else 0.0
        route = tuple(motion.route) if motion else tuple(self.runtime.route_updater.desired_routes.get(train_id, ()))
        block = motion.block_id if motion else str(train.get("block_id", "")) if self.simulation_mode else ""
        if not self.simulation_mode and motion is None:
            route = ()
        direction = 1 if self.runtime.track.get_train_direction(train_id) else -1
        connection = next_connection(block, route, direction)
        limit = self.runtime.track.get_train_speed_limit(train_id)
        effective = motion.target_speed if motion else self.runtime.track.get_effective_speed(train_id) if not self.simulation_mode else 0.0
        return {"requested_speed_kmh": round(requested * maximum, 4),
                "effective_speed_kmh": round(effective * maximum, 4),
                "actual_speed_kmh": round(motion.speed * maximum, 4) if motion and self.simulation_mode else None,
                "speed_limit_kmh": limit,
                "motion": {"block_id": block.lower(), "route": [item.lower() for item in route],
                           "position": motion.position if motion and self.simulation_mode else None,
                           "speed": motion.speed if motion and self.simulation_mode else None,
                           "effective_speed": effective,
                           "requested_speed": requested, "direction": direction,
                           "from_block_id": connection[0].lower() if connection else block.lower(),
                           "to_block_id": connection[1].lower() if connection else None,
                           "source": "simulation" if self.simulation_mode else "reported" if motion else "unknown",
                           "time_seconds": self.runtime.track.get_snapshot().time_seconds,
                           "tick_seconds": self.runtime.track.tick_seconds}}

    def _topology_edges(self) -> list[dict[str, Any]]:
        """Return editable block adjacency; turnout branches remain separately controlled."""

        links: set[tuple[str, str]] = set()
        explicit_topology = any("neighbor_ids" in block or "neighborIds" in block for block in self.blocks)
        if explicit_topology:
            for block in self.blocks:
                left = str(block.get("id", "")).strip().lower()
                for neighbour in block.get("neighbor_ids", block.get("neighborIds", ())):
                    right = str(neighbour).strip().lower()
                    if left and right and left != right:
                        links.add(tuple(sorted((left, right))))
        else:
            block_ids = [str(block.get("id", "")).strip().lower() for block in self.blocks if str(block.get("id", "")).strip()]
            if set(("b01", "b02", "b03", "b04")).issubset(block_ids):
                links.update({("b01", "b02"), ("b02", "b03"), ("b03", "b04")})
            else:
                links.update(tuple(sorted((left, right))) for left, right in zip(block_ids, block_ids[1:]))
        return [self._edge_with_geometry(left, right) for left, right in sorted(links)]

    def _ui_turnouts(self) -> list[dict[str, Any]]:
        locks = self.runtime.interlocking.locks if self.runtime is not None and hasattr(self.runtime, "interlocking") else {}
        return [
            {
                "id": "to1" if index == 0 else str(item.get("id", f"to{index + 1}")).lower(),
                "name": item.get("name", item.get("id", "Turnout")),
                "state": "straight" if item.get("state") in {"straight", "0", 0} else "diverging",
                "address": item.get("address"),
                "from": str(item.get("from", item.get("entry_block_id", ""))).lower(),
                "to": str(item.get("to", item.get("straight_block_id", ""))).lower(),
                "alternate": str(item.get("alternate", item.get("diverging_block_id", ""))).lower(),
                "lockedBy": self._ui_train_id(locks.get(str(item.get("id", "")).upper())) if locks.get(str(item.get("id", "")).upper()) else None,
            }
            for index, item in enumerate(self.turnouts)
        ]

    def _ui_train_id(self, canonical_id: str) -> str:
        return {"train-101": "t1", "train-3": "t2"}.get(canonical_id, canonical_id)

    def _canonical_train_id(self, ui_id: str) -> str:
        return {"t1": "train-101", "t2": "train-3"}.get(ui_id, ui_id)

    def _coupled_train_ids(self, train_id: str) -> list[str]:
        """Return the lead decoder followed by its paired locomotive decoders."""
        lead_id = self._canonical_train_id(str(train_id))
        lead = next((item for item in self.trains if str(item.get("id")) == lead_id), None)
        if lead is None:
            return [lead_id]
        parent_id = lead.get("coupled_to")
        if parent_id:
            parent_id = self._canonical_train_id(str(parent_id))
            parent = next((item for item in self.trains if str(item.get("id")) == parent_id), None)
            if parent is not None:
                lead_id = parent_id
                lead = parent
        raw_ids = lead.get("locomotive_ids", ())
        if not isinstance(raw_ids, (list, tuple)):
            raw_ids = ()
        result = [lead_id]
        for raw_id in raw_ids:
            member_id = self._canonical_train_id(str(raw_id))
            if member_id != lead_id and member_id not in result and any(str(item.get("id")) == member_id for item in self.trains):
                result.append(member_id)
        return result

    def _coupled_trains(self, train_id: str) -> list[dict[str, Any]]:
        ids = self._coupled_train_ids(train_id)
        return [train for train in self.trains if str(train.get("id")) in ids]

    def _next_schedule_destination(self, train: dict[str, Any]) -> str | None:
        """Resolve the next human-readable timetable destination for a train."""

        train_id = str(train.get("id", ""))
        address = str(train.get("address", train.get("number", "")))
        candidates: list[tuple[str, dict[str, Any]]] = []
        terminal_states = {"completed", "arrived", "cancelled", "canceled"}
        for schedule in self.schedules:
            schedule_train = schedule.get("train_id")
            if schedule_train not in (None, ""):
                if self._canonical_train_id(str(schedule_train)) != train_id:
                    continue
            elif str(schedule.get("number", "")) != address:
                continue
            if str(schedule.get("state", "")).strip().lower() in terminal_states:
                continue
            candidates.append((str(schedule.get("time", "99:99")), schedule))
        if not candidates:
            return None
        _, schedule = sorted(candidates, key=lambda item: item[0])[0]
        destination = str(schedule.get("destination", "")).strip()
        if destination:
            return destination
        route = str(schedule.get("route", "")).strip()
        if "→" in route:
            destination = route.rsplit("→", 1)[-1].strip()
            if destination:
                return destination
        stops = schedule.get("stops")
        if isinstance(stops, list) and stops:
            stop = stops[-1] if isinstance(stops[-1], dict) else {}
            station_id = stop.get("station_id", stop.get("stationId"))
        else:
            station_id = schedule.get("station_id", schedule.get("stationId"))
        if station_id not in (None, ""):
            station = next((item for item in self.stations if str(item.get("id")) == str(station_id)), None)
            return str((station or {}).get("name") or station_id)
        coordinate = schedule.get("destination_coordinate")
        if isinstance(coordinate, dict) and coordinate.get("x") is not None and coordinate.get("y") is not None:
            return f"Coordinate {coordinate['x']}, {coordinate['y']}"
        return None

    def _ui_trains(self) -> list[dict[str, Any]]:
        result = []
        for train in self.trains:
            ui_id = self._ui_train_id(train["id"])
            raw_length = train.get("length_mm")
            if raw_length in (None, ""):
                raw_length = 0
            try:
                display_length = float(raw_length)
                if display_length.is_integer():
                    display_length = int(display_length)
            except (TypeError, ValueError):
                display_length = 0
            max_speed = train.get("maxSpeed", train.get("max_speed_kmh", 140))
            if max_speed in (None, ""):
                max_speed = 140
            result.append({
                "id": ui_id,
                "number": "" if train.get("address") in (None, "") else str(train.get("address")),
                "name": train.get("name", ui_id),
                "mode": str(train.get("mode", "manual")),
                "class": "Automatic" if train.get("mode") == "automatic" else "Stopped" if train.get("mode") in {"stopped", "safe", "stop"} else "Manual",
                "status": "Stopped" if train.get("mode") in {"stopped", "safe", "stop"} else "Running" if train.get("speed", 0) else "Ready",
                "speed": train.get("speed", 0),
                "position": (
                    "Off graph" if not train.get("graph_enabled", True)
                    else train.get("block_id", "—")
                    if self.simulation_mode or any(m.train_id == train["id"] for m in self.runtime.track.get_snapshot().trains)
                    else "—"
                ),
                "graph_enabled": bool(train.get("graph_enabled", True)),
                "route": train.get("route", []),
                "destination_block_id": train.get("destination_block_id"),
                "scheduled_route_id": train.get("scheduled_route_id"),
                "scheduled_route_name": train.get("scheduled_route_name"),
                "origin": train.get("origin", "Layout"),
                "destination": train.get("destination", "Layout"),
                "next_destination": self._next_schedule_destination(train),
                "direction": "Forward" if (self.runtime.track.get_train_direction(str(train["id"])) if self.runtime else train.get("direction", "forward") == "forward") else "Reverse",
                "decoder": f"Z21-{train.get('address', '')}",
                "manufacturer": train.get("manufacturer", ""),
                "model_number": train.get("model_number", train.get("model", "")),
                "era": train.get("era", ""),
                "mass_g": train.get("mass_g"),
                "decoder_protocol": train.get("decoder_protocol", "DCC"),
                "length_mm": display_length,
                "length": display_length,
                "maxSpeed": max_speed,
                "consist": train.get("consist", []),
                "locomotive_ids": [self._ui_train_id(str(item)) for item in train.get("locomotive_ids", ()) if str(item)],
                "decoder_function_states": dict(train.get("decoder_function_states", {})),
                "target_coordinate": deepcopy(train.get("target_coordinate")) if train.get("target_coordinate") else None,
                **self._train_motion_state(train),
            })
        return result

    def advance_simulation(self, seconds: float, rate: float = 1) -> dict[str, Any]:
        """Deliberate fast-forward uses real simulated seconds, never hardware."""
        if not self.simulation_mode:
            raise ValueError("Fast-forward is only available in simulation")
        if not math.isfinite(seconds) or not math.isfinite(rate) or seconds <= 0 or rate <= 0 or seconds * rate > 600:
            raise ValueError("Choose a positive simulation interval of at most 600 seconds")
        with self._lock:
            interval = self.runtime.track.tick_seconds
            remaining = max(1, math.ceil(seconds * rate / interval))
            while remaining:
                count = min(100, remaining)
                self.tick(count, elapsed_seconds=count * interval, force=True)
                remaining -= count
            return self._ui_snapshot()

    def tick(self, steps: int = 1, *, elapsed_seconds: float | None = None, force: bool = False) -> dict[str, Any]:
        with self._lock:
            safe_steps = max(1, min(int(steps), 100))
            if self.simulation_mode and not self.simulation_running and not force:
                self.events.append({"type": "simulation_tick_skipped", "reason": "simulation paused"})
                return self._ui_snapshot()
            if self.runtime is not None:
                scheduler_was_running = self.runtime.scheduler.running
                if force and self.simulation_mode and not scheduler_was_running:
                    self.runtime.scheduler.start(
                        tick=self.runtime.scheduler.current_tick,
                        world_tick=self.runtime.scheduler.world_current_tick,
                    )
                self.runtime.tick(safe_steps)
                if elapsed_seconds is None:
                    self._world_clock_seconds += safe_steps * 60
                    if self.runtime.scheduler.running:
                        self.runtime.scheduler.advance(safe_steps)
                        schedule_events = self.runtime.scheduler.advance_world(safe_steps)
                    else:
                        schedule_events = ()
                else:
                    # One real second advances the model world by one minute.
                    # That produces a 24-minute model day while the simulation
                    # clock continues to show ordinary elapsed seconds.
                    self._world_clock_seconds += max(0.0, elapsed_seconds) * 60
                    schedule_steps = 0
                    if self.runtime.scheduler.running:
                        self._scheduler_remainder_seconds += elapsed_seconds
                        schedule_steps = int((self._scheduler_remainder_seconds + 1e-9) // 60)
                        self._scheduler_remainder_seconds -= schedule_steps * 60
                        # Keep the legacy simulation-minute counter available
                        # for explicit diagnostics and existing integrations.
                        self.runtime.scheduler.advance(schedule_steps)
                    world_target_tick = int(self._world_clock_seconds // 60)
                    world_steps = max(0, world_target_tick - self.runtime.scheduler.world_current_tick)
                    schedule_events = self.runtime.scheduler.advance_world(world_steps) if self.runtime.scheduler.running else ()
                for schedule_event in schedule_events:
                    state = "Arrived" if schedule_event.kind.value == "arrival" else "Departed"
                    schedule_id = str(schedule_event.stop.stop_id).split("#", 1)[0]
                    row = next((item for item in self.schedules if item.get("id") == schedule_id), None)
                    if row is not None:
                        row["state"] = state
                        if schedule_event.kind.value == "departure":
                            dispatch_mode = str(row.get("dispatch_mode", "") or "").lower()
                            if dispatch_mode == "route" or row.get("route_id"):
                                self._schedule_route_target(row, schedule_event.stop.stop_id, schedule_event.stop.train_id)
                            elif dispatch_mode == "coordinate" or row.get("destination_coordinate"):
                                self._schedule_coordinate_target(row, schedule_event.stop.stop_id, schedule_event.stop.train_id)
                    self._publish_domain_event(
                        ScheduleStateChanged(
                            schedule_id=schedule_id,
                            status=ScheduleStatus.COMPLETED if state == "Arrived" else ScheduleStatus.ACTIVE,
                        )
                    )
                    self.events.append({"type": f"schedule_{schedule_event.kind.value}", "schedule_id": schedule_id, "stop_id": schedule_event.stop.stop_id, "train_id": schedule_event.stop.train_id, "tick": schedule_event.tick})
                if force and self.simulation_mode and not scheduler_was_running:
                    self.runtime.scheduler.pause()
                self._sync_ui_from_runtime()
                self.tick_count = self.runtime.track.get_snapshot().tick
            else:
                for _ in range(safe_steps):
                    self.tick_count += 1
                    for train in self.trains:
                        if train["mode"] == "automatic" and train["speed"] > 0:
                            train["progress"] = (train.get("progress", 0) + train["speed"] / 100) % 1
            self.events.append({"type": "simulation_tick", "tick": self.tick_count})
            self._routing_wake.set()
            return self._ui_snapshot()

    def save_layout(self, layout_id: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        """Persist the current editor state through the typed layout repository."""

        if self.runtime is None:
            raise RuntimeError("runtime is not available")
        selected_id = (layout_id or self.layout_id).strip()
        if not selected_id:
            raise ValueError("layout_id is required")
        self._sync_runtime_from_ui()
        self.layout_id = selected_id
        if name:
            self.layout_name = name.strip() or self.layout_name
        record = self.runtime.layout_repository.save(selected_id, self.runtime.layout.snapshot().snapshot, name=self.layout_name)
        self.events.append({"type": "layout_saved", "layout_id": record.layout_id, "revision": record.revision})
        return {"layout_id": record.layout_id, "name": record.name, "revision": record.revision, "updated_at": record.updated_at}

    def load_layout(self, layout_id: str | None = None) -> dict[str, Any] | None:
        """Load one saved domain snapshot and project it into the dashboard state."""

        if self.runtime is None:
            raise RuntimeError("runtime is not available")
        selected_id = (layout_id or self.layout_id).strip()
        snapshot = self.runtime.layout_repository.load(selected_id)
        if snapshot is None:
            return None
        projected = snapshot_to_ui(snapshot)
        self.blocks = projected["blocks"]
        self.trains = projected["trains"]
        self.turnouts = projected["turnouts"]
        self.stations = projected.get("stations", [])
        self.signals = projected.get("signals", [])
        self.waypoints = projected.get("waypoints", [])
        self.turntables = projected.get("turntables", [])
        self.platforms = projected.get("platforms", [])
        self.schedules = projected.get("schedules", [])
        self.routes = projected.get("routes", [])
        self.scans = projected.get("scans", self.scans)
        self.connection_limits = projected.get("connection_limits", [])
        if self.z21_host:
            self.runtime.dispatcher.emergency_stop()
            for train in self.trains:
                train.update(mode="stopped", speed=0, requested_speed_kmh=0)
        self.layout_id = selected_id
        self.layout_name = next((record.name for record in self.runtime.layout_repository.list() if record.layout_id == selected_id), f"Saved layout {selected_id}")
        self._sync_runtime_from_ui()
        self.events.append({"type": "layout_loaded", "layout_id": selected_id, "revision": snapshot.revision})
        return self.state()

    @staticmethod
    def _layout_asset_id(value: Any, asset_type: str) -> str:
        """Normalize one layout-asset ID at the UI/domain boundary."""

        normalized = str(value).strip().upper() if value is not None else ""
        if not normalized:
            raise ValueError(f"{asset_type} ID is required")
        return normalized

    @staticmethod
    def _layout_asset_id_list(value: Any, field_name: str) -> list[str]:
        """Normalize a UI list of layout-asset references."""

        if value in (None, ""):
            return []
        if not isinstance(value, (list, tuple, set)):
            raise ValueError(f"{field_name} must be a list")
        return [str(item).strip().upper() for item in value if str(item).strip()]

    @staticmethod
    def _first_layout_value(values: dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in values:
                return values[key]
        return default

    def _normalize_layout_asset(self, asset_type: str, raw: dict[str, Any], *, defaults: bool = True, require_id: bool = True) -> dict[str, Any]:
        """Project a UI asset dictionary into the canonical UI dictionary shape."""

        item = dict(raw)
        if require_id or "id" in item:
            item["id"] = self._layout_asset_id(item.get("id"), asset_type)
        display_id = item.get("id", asset_type)
        if asset_type == "station":
            if defaults or "name" in item:
                item["name"] = str(item.get("name", display_id)).strip() or display_id
            for canonical, aliases in (
                ("blockIds", ("blockIds", "block_ids")),
                ("platformIds", ("platformIds", "platform_ids")),
                ("waypointIds", ("waypointIds", "waypoint_ids")),
            ):
                value = self._first_layout_value(item, *aliases, default=None)
                if value is not None or defaults:
                    item[canonical] = self._layout_asset_id_list(value, canonical)
                for alias in aliases:
                    if alias != canonical:
                        item.pop(alias, None)
        elif asset_type == "signal":
            if defaults or "name" in item:
                item["name"] = str(item.get("name", display_id)).strip() or display_id
            for canonical, aliases in (
                ("block_id", ("block_id", "blockId")),
                ("protects_block_id", ("protects_block_id", "protectsBlockId", "protects")),
            ):
                value = self._first_layout_value(item, *aliases, default=None)
                if value is not None or defaults:
                    item[canonical] = str(value).strip().upper() if value not in (None, "") else ""
                for alias in aliases:
                    if alias != canonical:
                        item.pop(alias, None)
            if defaults or "aspect" in item:
                aspect = str(item.get("aspect", "red")).strip().lower()
                try:
                    SignalAspect(aspect)
                except ValueError as exc:
                    raise ValueError(f"unsupported signal aspect: {aspect}") from exc
                item["aspect"] = aspect
            if defaults or "address" in item:
                if item.get("address") in (None, ""):
                    item["address"] = None
            if defaults and (not item.get("block_id") or not item.get("protects_block_id")):
                raise ValueError("signal requires block_id and protects_block_id")
        elif asset_type == "waypoint":
            if defaults or "name" in item:
                item["name"] = str(item.get("name", display_id)).strip() or display_id
            value = self._first_layout_value(item, "connected_node_ids", "connectedNodeIds", "connected", default=None)
            if value is not None or defaults:
                item["connected_node_ids"] = self._layout_asset_id_list(value, "connected_node_ids")
            for alias in ("connectedNodeIds", "connected"):
                item.pop(alias, None)
        elif asset_type == "turntable":
            if defaults or "name" in item:
                item["name"] = str(item.get("name", display_id)).strip() or display_id
            value = self._first_layout_value(item, "connected_block_ids", "connectedBlockIds", "connected", default=None)
            if value is not None or defaults:
                item["connected_block_ids"] = self._layout_asset_id_list(value, "connected_block_ids")
            for alias in ("connectedBlockIds", "connected"):
                item.pop(alias, None)
            if defaults or "aligned_block_id" in item or "alignedBlockId" in item:
                aligned = self._first_layout_value(item, "aligned_block_id", "alignedBlockId", default=None)
                item["aligned_block_id"] = str(aligned).strip().upper() if aligned not in (None, "") else None
                item.pop("alignedBlockId", None)
            if defaults or "occupied_by" in item:
                occupied_by = item.get("occupied_by")
                item["occupied_by"] = self._canonical_train_id(str(occupied_by).strip()) if occupied_by not in (None, "") else None
            if defaults or "address" in item:
                if item.get("address") in (None, ""):
                    item["address"] = None
            if defaults and not item.get("connected_block_ids"):
                raise ValueError("turntable requires connected_block_ids")
        elif asset_type == "turnout":
            if defaults or "name" in item:
                item["name"] = str(item.get("name", display_id)).strip() or display_id
            for canonical, aliases in (
                ("from", ("from", "entry_block_id", "entry")),
                ("to", ("to", "straight_block_id", "straight")),
                ("alternate", ("alternate", "diverging_block_id", "diverging")),
            ):
                value = self._first_layout_value(item, *aliases, default=None)
                if value is not None or defaults:
                    item[canonical] = str(value).strip().upper() if value not in (None, "") else ""
                for alias in aliases:
                    if alias != canonical:
                        item.pop(alias, None)
            if defaults or "state" in item:
                item["state"] = str(item.get("state", "straight")).strip().lower() or "straight"
            if defaults or "address" in item:
                if item.get("address") in (None, ""):
                    item["address"] = None
            if defaults and not all(item.get(field) for field in ("from", "to", "alternate")):
                raise ValueError("turnout requires from, to, and alternate block IDs")
        elif asset_type == "platform":
            if defaults or "name" in item:
                item["name"] = str(item.get("name", display_id)).strip() or display_id
            station_id = self._first_layout_value(item, "stationId", "station_id", default=None)
            block_id = self._first_layout_value(item, "blockId", "block_id", default=None)
            if block_id in (None, ""):
                block_ids = self._first_layout_value(item, "blockIds", "block_ids", default=None)
                normalized_block_ids = self._layout_asset_id_list(block_ids, "blockIds")
                block_id = normalized_block_ids[0] if normalized_block_ids else None
            if station_id is not None or defaults:
                item["stationId"] = str(station_id).strip().upper() if station_id not in (None, "") else ""
            if block_id is not None or defaults:
                item["blockId"] = str(block_id).strip().upper() if block_id not in (None, "") else ""
            for alias in ("station_id", "block_id", "blockIds", "block_ids"):
                item.pop(alias, None)
            if defaults or "lengthMm" in item or "length_mm" in item:
                length = self._first_layout_value(item, "lengthMm", "length_mm", default=0)
                item["lengthMm"] = length
                item.pop("length_mm", None)
            if defaults and (not item.get("stationId") or not item.get("blockId")):
                raise ValueError("platform requires stationId and blockId")
        return item

    def _validate_layout_asset_state(self, collections: dict[str, list[dict[str, Any]]], *, removed_type: str | None = None, removed_id: str | None = None) -> LayoutSnapshot:
        """Validate candidate UI collections using the immutable domain snapshot."""

        try:
            snapshot = snapshot_from_ui(
                blocks=self.blocks,
                turnouts=collections.get("turnouts", self.turnouts),
                trains=self.trains,
                schedules=self.schedules,
                routes=self.routes,
                edges=self._topology_edges(),
                stations=collections.get("stations", self.stations),
                signals=collections.get("signals", self.signals),
                waypoints=collections.get("waypoints", self.waypoints),
                turntables=collections.get("turntables", self.turntables),
                platforms=collections.get("platforms", self.platforms),
                scans=self.scans,
                connection_limits=self.connection_limits,
                revision=self.runtime.layout.snapshot().version if self.runtime is not None else 0,
            )
        except KeyError as exc:
            raise ValueError(f"layout asset references unknown ID: {exc.args[0]}") from exc
        if removed_type == "station" and removed_id:
            for row in self.schedules:
                direct_station = row.get("station_id", row.get("stationId"))
                if direct_station not in (None, "") and self._layout_asset_id(direct_station, "station") == removed_id:
                    raise ValueError(f"cannot remove station {removed_id}: it is referenced by schedule {row.get('id', '')}")
                for stop in row.get("stops", ()) if isinstance(row.get("stops", ()), (list, tuple)) else ():
                    if isinstance(stop, dict):
                        stop_station = stop.get("station_id", stop.get("stationId"))
                        if stop_station not in (None, "") and self._layout_asset_id(stop_station, "station") == removed_id:
                            raise ValueError(f"cannot remove station {removed_id}: it is referenced by a schedule stop")
        return snapshot

    def _command_layout_asset(self, kind: str, payload: dict[str, Any]) -> bool:
        """Handle CRUD for one of the five editable layout asset collections."""

        parts = kind.split("_", 1)
        if len(parts) != 2 or parts[0] not in {"add", "update", "remove", "delete"} or parts[1] not in {"station", "signal", "waypoint", "turnout", "turntable", "platform"}:
            return False
        operation = "remove" if parts[0] == "delete" else parts[0]
        asset_type = parts[1]
        collection_name = f"{asset_type}s"
        collection = list(getattr(self, collection_name))
        entity_key = asset_type
        raw_entity = payload.get(entity_key, {})
        if raw_entity is None:
            raw_entity = {}
        if not isinstance(raw_entity, dict):
            raise ValueError(f"{entity_key} must be an object")
        raw_entity = dict(raw_entity)

        selected_value = payload.get(f"{asset_type}_id", payload.get("id", raw_entity.get("id")))
        selected_id = self._layout_asset_id(selected_value, asset_type)
        existing_index = next((index for index, item in enumerate(collection) if str(item.get("id", "")).strip().upper() == selected_id), None)
        if operation == "add":
            if existing_index is not None:
                raise ValueError(f"{asset_type} ID must be unique")
            raw_entity.setdefault("id", selected_id)
            entity = self._normalize_layout_asset(asset_type, raw_entity)
            collection.append(entity)
        elif existing_index is None:
            raise ValueError(f"Unknown {asset_type}: {selected_id}")
        elif operation == "update":
            if "id" in raw_entity and self._layout_asset_id(raw_entity["id"], asset_type) != selected_id:
                raise ValueError(f"{asset_type} ID cannot be changed")
            existing = self._normalize_layout_asset(asset_type, collection[existing_index])
            updates = self._normalize_layout_asset(asset_type, raw_entity, defaults=False, require_id=False)
            updates["id"] = selected_id
            existing.update(updates)
            collection[existing_index] = self._normalize_layout_asset(asset_type, existing)
        else:
            collection.pop(existing_index)

        candidates = {collection_name: collection}
        self._validate_layout_asset_state(candidates, removed_type=asset_type if operation == "remove" else None, removed_id=selected_id if operation == "remove" else None)
        previous = getattr(self, collection_name)
        setattr(self, collection_name, collection)
        try:
            self._sync_runtime_from_ui()
        except Exception:
            setattr(self, collection_name, previous)
            raise
        self.events.append({"type": f"{asset_type}_{'removed' if operation == 'remove' else 'added' if operation == 'add' else 'updated'}", f"{asset_type}_id": selected_id})
        return True

    def _normalize_route_flow(self, raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
        """Normalize reusable route blocks and extract only optional graph nodes."""
        if raw is None:
            return [], []
        if not isinstance(raw, (list, tuple)):
            raise ValueError("route flow must be a list")
        graph = self.runtime.layout.graph() if self.runtime is not None else None
        flow: list[dict[str, Any]] = []
        node_ids: list[str] = []
        for raw_block in raw:
            if not isinstance(raw_block, dict):
                raise ValueError("route flow blocks must be objects")
            kind = str(raw_block.get("type", raw_block.get("kind", ""))).strip().lower()
            if kind == "program":
                kind = "routine"
            if kind == "node":
                node_id = str(raw_block.get("node_id", raw_block.get("value", ""))).strip().upper()
                if not node_id or graph is None or graph.node(node_id) is None:
                    raise ValueError("route node blocks must reference graph nodes")
                flow.append({"type": "node", "node_id": node_id})
                node_ids.append(node_id)
            elif kind == "routine":
                program_id = str(raw_block.get("program_id", raw_block.get("value", ""))).strip()
                if not program_id:
                    raise ValueError("routine blocks require a program_id")
                flow.append({"type": "routine", "program_id": program_id})
            elif kind in {"sync", "sync_locomotive"}:
                locomotive_id = str(raw_block.get("locomotive_id", raw_block.get("train_id", raw_block.get("value", "")))).strip()
                canonical_id = self._canonical_train_id(locomotive_id)
                if not locomotive_id or not any(str(item.get("id")) == canonical_id for item in self.trains):
                    raise ValueError("sync blocks must reference a known locomotive")
                flow.append({"type": "sync", "locomotive_id": locomotive_id})
            else:
                raise ValueError("route flow block type must be node, routine, or sync")
        return flow, node_ids

    def _route_path(self, source: Any, target: Any, algorithm: Any = "a_star", requested: Any = None) -> tuple[list[str], str]:
        """Validate a saved route path or calculate one through the live graph."""

        if self.runtime is None:
            raise ValueError("runtime is not available")
        graph = self.runtime.layout.graph()
        source_id = str(source or "").strip().upper()
        target_id = str(target or "").strip().upper()
        if not source_id or not target_id:
            raise ValueError("route source and target are required")
        if graph.node(source_id) is None or graph.node(target_id) is None:
            raise ValueError("route source and target must be graph nodes")
        selected = str(algorithm or "a_star").strip().lower()
        if selected not in {RouteAlgorithm.A_STAR.value, RouteAlgorithm.BFS.value}:
            raise ValueError("route algorithm must be a_star or bfs")
        if requested is not None:
            if not isinstance(requested, (list, tuple)):
                raise ValueError("route node_ids must be a list")
            path = tuple(str(item).strip().upper() for item in requested if str(item).strip())
            if not path or path[0] != source_id or path[-1] != target_id:
                raise ValueError("route node_ids must start at source and end at target")
            if any(graph.node(node_id) is None for node_id in path):
                raise ValueError("route node_ids must reference graph nodes")
            if len(set(path)) != len(path):
                raise ValueError("route node_ids must not repeat graph nodes")
            if any(not any(edge.target_id == right for edge in graph.neighbors(left)) for left, right in zip(path, path[1:])):
                raise ValueError("route node_ids must follow connected track edges")
            return list(path), selected
        route = find_route(graph, source_id, target_id, algorithm=RouteAlgorithm(selected))
        if route is None:
            fallback = RouteAlgorithm.BFS if selected == RouteAlgorithm.A_STAR.value else RouteAlgorithm.A_STAR
            route = find_route(graph, source_id, target_id, algorithm=fallback)
        if route is None:
            raise ValueError(f"No route from {source_id} to {target_id}")
        return list(route.node_ids), route.algorithm.value

    def command(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            kind = str(payload.get("type", "")).lower()
            if kind == "set_connection_speed_limit":
                left = str(payload.get("from", payload.get("from_block_id", ""))).strip().upper()
                right = str(payload.get("to", payload.get("to_block_id", ""))).strip().upper()
                if not any(c["from"].upper() == left and c["to"].upper() == right for c in self._ui_connections()):
                    raise ValueError("speed limit requires an existing directed connection")
                rows = deepcopy(self.connection_limits)
                rule = next((r for r in rows if (r["from"], r["to"]) == (left, right)), None)
                if rule is None:
                    rule = {"from": left, "to": right, "speed_limit_kmh": None, "train_speed_limits": {}}
                    rows.append(rule)
                if "train_id" in payload:
                    train_id = self._canonical_train_id(str(payload["train_id"]))
                    if not any(t["id"] == train_id for t in self.trains):
                        raise ValueError("unknown train for connection speed limit")
                    if "speed_limit_kmh" not in payload:
                        raise ValueError("speed_limit_kmh is required; null removes an override")
                    if payload["speed_limit_kmh"] is None:
                        rule["train_speed_limits"].pop(train_id, None)
                    else:
                        rule["train_speed_limits"][train_id] = payload["speed_limit_kmh"]
                else:
                    if "speed_limit_kmh" in payload:
                        rule["speed_limit_kmh"] = payload["speed_limit_kmh"]
                    if "train_speed_limits" in payload:
                        if not isinstance(payload["train_speed_limits"], dict):
                            raise ValueError("train_speed_limits must be an object")
                        rule["train_speed_limits"] = {self._canonical_train_id(key): value for key, value in payload["train_speed_limits"].items()}
                candidate = snapshot_from_ui(**{key: getattr(self, key) for key in
                    ("blocks", "turnouts", "trains", "schedules", "routes", "stations", "signals", "waypoints", "turntables", "platforms", "scans")},
                    edges=self._topology_edges(), connection_limits=rows)
                self.connection_limits = snapshot_to_ui(candidate)["connection_limits"]
                self.runtime.layout.replace(candidate)
                self._apply_speed_policy(candidate)
                self._sync_ui_from_runtime()
                self.events.append({"type": "connection_speed_limit_changed", "from": left, "to": right})
            elif kind == "report_train_position":
                if self.simulation_mode:
                    raise ValueError("simulator positions are determined by movement, not position reports")
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((t for t in self.trains if t["id"] == train_id), None)
                block = str(payload.get("block_id", "")).strip().upper()
                route = tuple(str(item).upper() for item in payload.get("route", ()))
                graph = self.runtime.layout.graph()
                if train is None or graph.node(block) is None or block not in route:
                    raise ValueError("known train, block and route containing that block are required")
                if any(not any(e.target_id == right for e in graph.neighbors(left)) for left, right in zip(route, route[1:])):
                    raise ValueError("reported route must follow existing connections")
                result = self.runtime.track.report_train_position(train_id, block, route)
                if not result.accepted:
                    self.runtime.dispatcher.emergency_stop()
                    raise ValueError(result.detail or "could not apply speed limit at reported position")
                train["block_id"] = block
                train["route"] = list(route)
                self.runtime.route_updater.set_route(train_id, route)
                self._sync_ui_from_runtime()
            elif kind in {"start_calibration", "calibrate_train"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                if self.runtime is None or not self.track_power:
                    raise ValueError("switch track power on before starting calibration")
                self.runtime.calibration.set_max_speed(float(train.get("maxSpeed", train.get("max_speed_kmh", 140)) or 140))
                run = self.runtime.calibration.start(
                    train_id,
                    speed_kmh=float(payload.get("speed_kmh", 10)),
                    duration_ms=int(payload.get("duration_ms", 100)),
                )
                train["mode"] = ControlMode.MANUAL.value
                train["speed"] = 0
                self.events.append({"type": "calibration_started", "run_id": run.run_id, "train_id": train_id})
            elif kind in {"scan_train_presence", "ping_train_addresses", "detect_trains"}:
                self._start_presence_scan()
            elif kind in {"start_recording", "begin_recording"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                if not any(item.get("id") == train_id for item in self.trains):
                    raise ValueError(f"Unknown train: {train_id}")
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                self.runtime.recording.start(train_id, timestamp=float(payload.get("timestamp", time.time())))
                self.events.append({"type": "recording_started", "train_id": train_id})
            elif kind in {"record_action", "record_train_action"}:
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                action = payload.get("action", payload)
                if not isinstance(action, dict):
                    raise ValueError("action must be an object")
                action = dict(action)
                if action.get("train_id"):
                    action["train_id"] = self._canonical_train_id(str(action["train_id"]))
                timestamp = None if "timestamp" in action else payload.get("timestamp")
                self.runtime.recording.append(action, timestamp=None if timestamp is None else float(timestamp))
            elif kind in {"stop_recording", "end_recording"}:
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                plan = self.runtime.recording.stop(timestamp=float(payload.get("timestamp", time.time())))
                self._recording_history.append(plan)
                self.events.append({"type": "recording_stopped", "train_id": plan.train_id, "action_count": plan.action_count})
            elif kind in {"play_recording", "playback_recording"}:
                self.play_recording(payload)
            elif kind in {"save_automation_program", "upsert_automation_program"}:
                self.save_automation_program(payload)
            elif kind in {"delete_automation_program", "remove_automation_program"}:
                program_id = str(payload.get("program_id", payload.get("id", ""))).strip()
                before = len(self._automation_programs)
                self._automation_programs = [item for item in self._automation_programs if item.get("id") != program_id]
                if len(self._automation_programs) == before:
                    raise ValueError("automation program not found")
                self.events.append({"type": "automation_program_deleted", "program_id": program_id})
            elif kind in {"play_automation_program", "run_automation_program"}:
                self.play_automation_program(payload)
            elif kind in {"place_train_on_track", "place_train"}:
                if not self.simulation_mode:
                    raise ValueError("placing a train on a coordinate is available in simulation only")
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item.get("id") == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                if self.runtime is None or not hasattr(self.runtime.track, "place_train"):
                    raise ValueError("simulation track placement is unavailable")
                try:
                    x, y = float(payload.get("x")), float(payload.get("y"))
                except (TypeError, ValueError) as exc:
                    raise ValueError("x and y coordinates are required") from exc
                coordinate = nearest_track_coordinate(self.blocks, self._topology_edges(), x, y)
                if coordinate is None:
                    raise ValueError("coordinate is not on a configured track segment")
                occupied = {
                    str(motion.block_id).upper(): motion.train_id
                    for motion in self.runtime.track.get_snapshot().trains
                }
                source = coordinate.from_node.upper()
                occupant = occupied.get(source)
                if occupant is not None and occupant != train_id:
                    raise ValueError(f"track block {source} is occupied by {self._ui_train_id(occupant)}")
                route = (source, coordinate.to_node.upper())
                result = self.runtime.track.place_train(
                    train_id,
                    source,
                    coordinate.progress,
                    route=route,
                    direction=1,
                )
                if hasattr(result, "accepted") and not result.accepted:
                    raise ValueError(result.detail or "train placement was rejected")
                control = self.runtime.dispatcher.register_train(train_id)
                control.mode = ControlMode.STOPPED
                control.manual_speed = control.automatic_speed = 0.0
                train.update({
                    "block_id": source,
                    "route": [source, route[1]],
                    "mode": ControlMode.STOPPED.value,
                    "speed": 0,
                    "requested_speed_kmh": 0,
                    "target_coordinate": None,
                    "graph_enabled": True,
                })
                self.events.append({
                    "type": "train_placed_on_track",
                    "train_id": train_id,
                    "coordinate": {
                        "x": round(coordinate.x, 2), "y": round(coordinate.y, 2),
                        "from_node": coordinate.from_node.lower(), "to_node": coordinate.to_node.lower(),
                        "progress": round(coordinate.progress, 6),
                    },
                })
            elif kind in {"upsert_rolling_stock_inventory", "set_rolling_stock_inventory"}:
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                item = RollingStockInventoryRecord(
                    item_id=str(payload.get("item_id", payload.get("id", ""))).strip(),
                    name=str(payload.get("name", "")).strip(),
                    vehicle_type=str(payload.get("vehicle_type", payload.get("type", "vehicle"))).strip() or "vehicle",
                    quantity=int(payload.get("quantity", payload.get("count", 0))),
                    manufacturer=str(payload.get("manufacturer", "")), model=str(payload.get("model", "")),
                    length_mm=payload.get("length_mm"), mass_g=payload.get("mass_g"),
                    metadata=dict(payload.get("metadata", {})),
                )
                self.runtime.train_database.upsert_inventory(item)
                self.events.append({"type": "rolling_stock_inventory_updated", "item_id": item.item_id, "quantity": item.quantity})
            elif kind in {"adjust_rolling_stock_inventory", "change_rolling_stock_quantity"}:
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                item_id = str(payload.get("item_id", payload.get("id", ""))).strip()
                item = self.runtime.train_database.adjust_inventory(
                    item_id, int(payload.get("delta", payload.get("change", 0))),
                    **{key: payload[key] for key in ("name", "vehicle_type", "manufacturer", "model", "length_mm", "mass_g", "metadata") if key in payload},
                )
                self.events.append({"type": "rolling_stock_inventory_updated", "item_id": item.item_id, "quantity": item.quantity})
            elif kind in {"request_programming", "validate_programming"}:
                self.request_decoder_programming(payload)
            elif kind in {"request_dcc_address_programming", "validate_dcc_address"}:
                self.request_dcc_address_programming(payload)
            elif kind in {"program_decoder", "program_cv"}:
                if payload.get("confirm") is True:
                    self.execute_decoder_programming(payload)
                else:
                    self.request_decoder_programming(payload)
            elif kind in {"program_dcc_address", "program_decoder_address"}:
                if payload.get("confirm") is True:
                    self.execute_dcc_address_programming(payload)
                else:
                    self.request_dcc_address_programming(payload)
            elif kind in {"read_decoder_cv", "read_cv"}:
                self.read_decoder_cv(payload)
            elif kind in {"cancel_calibration", "stop_calibration"}:
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                run = self.runtime.calibration.cancel()
                if run is not None:
                    self.events.append({"type": "calibration_cancelled", "run_id": run.run_id, "train_id": run.train_id})
            elif kind in {"record_calibration", "record_calibration_distance"}:
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                record = self.runtime.calibration.record_distance(
                    float(payload.get("distance_mm", payload.get("measured_distance_mm"))),
                    notes=str(payload.get("notes", "")),
                )
                self.events.append({"type": "calibration_recorded", "calibration_id": record.calibration_id, "train_id": record.train_id})
            elif kind in {"move_train_to_coordinate", "move_to_coordinate"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                if self.runtime is None:
                    raise ValueError("controller runtime unavailable")
                try:
                    x, y = float(payload.get("x")), float(payload.get("y"))
                except (TypeError, ValueError) as exc:
                    raise ValueError("x and y coordinates are required") from exc
                control = self.runtime.dispatcher.register_train(train_id)
                if control.mode is ControlMode.AUTOMATIC:
                    raise ValueError("switch this train to manual control before dragging it")
                motion = next((item for item in self.runtime.track.get_snapshot().trains if item.train_id == train_id), None)
                if float(train.get("speed", 0) or 0) > 0 or control.desired_speed > 0 or (motion and (motion.speed > 0 or motion.target_speed > 0)):
                    raise ValueError("stop the train before dragging it to a coordinate")
                current = str((motion.block_id if motion else train.get("block_id", "")) or "").strip().upper()
                direction = "forward" if self.runtime.track.get_train_direction(train_id) else "reverse"
                calibration = self.runtime.calibration.history(train_id)
                if not calibration:
                    raise ValueError("record a calibration measurement for this train before coordinate movement")
                try:
                    planner_blocks = [{**block, "id": str(block.get("id", "")).strip().upper()} for block in self.blocks]
                    planner_edges = [{**edge, "from": str(edge.get("from", "")).strip().upper(), "to": str(edge.get("to", "")).strip().upper()} for edge in self._topology_edges()]
                    planner = CoordinateMovementPlanner(planner_blocks, planner_edges, calibration)
                    destination = planner.plan(
                        train_id, x, y, speed_kmh=10, direction=direction,
                        occupied_blocks=self.runtime.track.get_snapshot().occupied_blocks,
                    )
                    if current:
                        route_prefix, _ = self._route_path(current, destination.source_block_id)
                        configured_blocks = {str(block["id"]).upper() for block in planner_blocks}
                        if any(node_id not in configured_blocks for node_id in route_prefix):
                            raise ValueError("coordinate movement supports clear block-to-block routes only")
                    else:
                        route_prefix = [destination.source_block_id]
                    plan = planner.plan(
                        train_id, x, y, speed_kmh=10, direction=direction,
                        occupied_blocks=self.runtime.track.get_snapshot().occupied_blocks,
                        current_block_id=current or None, route_node_ids=route_prefix,
                    )
                except MovementPlanValidationError as exc:
                    raise ValueError(str(exc)) from exc
                target = {"x": round(plan.x, 2), "y": round(plan.y, 2),
                          "from_node": plan.source_block_id.lower(), "to_node": plan.target_block_id.lower(),
                          "progress": round(plan.progress, 6), "distance_mm": round(plan.distance_mm, 2),
                          "estimated_duration_ms": plan.estimated_duration_ms, "direction": plan.direction,
                          "speed_kmh": plan.speed_kmh,
                          "route_node_ids": [item.lower() for item in plan.route_node_ids]}
                train["target_coordinate"] = target
                route = plan.route_node_ids
                train["route"] = [item.lower() for item in route]
                self.runtime.route_updater.set_route(train_id, route)
                if self.simulation_mode and hasattr(self.runtime.track, "set_train_route"):
                    result = self.runtime.track.set_train_route(train_id, route)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "coordinate route was rejected")
                self.events.append({"type": "train_coordinate_targeted", "train_id": train_id, "coordinate": target})
            elif kind in {"execute_coordinate_move", "run_coordinate_move"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None or self.runtime is None:
                    raise ValueError("a known train and active runtime are required")
                if not self.simulation_mode and payload.get("confirm") is not True:
                    raise ValueError("real-track coordinate movement requires confirm=true")
                target = train.get("target_coordinate")
                if not isinstance(target, dict):
                    raise ValueError("create a coordinate target before executing movement")
                calibration = self.runtime.calibration.history(train_id)
                if not calibration:
                    raise ValueError("record a calibration measurement for this train before coordinate movement")
                try:
                    from backend.services.coordinate_move import CoordinateMovementPlan
                    movement_plan = CoordinateMovementPlan(
                        train_id=train_id, x=float(target["x"]), y=float(target["y"]),
                        source_block_id=str(target["from_node"]).upper(), target_block_id=str(target["to_node"]).upper(),
                        progress=float(target.get("progress", 0)), distance_mm=float(target["distance_mm"]),
                        speed_kmh=float(target.get("speed_kmh", 10)), estimated_duration_ms=int(target.get("estimated_duration_ms", 1)),
                        segment_length_mm=max(1.0, float(target["distance_mm"])), calibration_speed_kmh=float(calibration[0].speed_kmh),
                        calibration_duration_ms=int(calibration[0].duration_ms), direction=str(target.get("direction", train.get("direction", "forward"))),
                        route_node_ids=tuple(str(item).upper() for item in target.get("route_node_ids", ()) if str(item).strip()),
                    )
                    execution = CoordinateMovementExecutionPlanner(max_duration_ms=120000).build(movement_plan, calibration)
                except (KeyError, TypeError, ValueError, MovementPlanValidationError) as exc:
                    raise ValueError(str(exc)) from exc
                if not self.track_power:
                    raise ValueError("switch track power on before coordinate movement")
                status = self.runtime.coordinate_movement.start(execution, confirmed=True)
                self._coordinate_execution_state = status.as_dict()
                self.events.append({"type": "train_coordinate_execution_started", "train_id": train_id, "duration_ms": execution.duration_ms})
            elif kind == "set_direction":
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                direction = payload.get("direction")
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                if direction not in ("forward", "reverse"):
                    raise ValueError("direction must be forward or reverse")
                if self.runtime is None:
                    raise ValueError("controller runtime unavailable")
                control = self.runtime.dispatcher.register_train(train_id)
                if control.mode is ControlMode.AUTOMATIC:
                    raise ValueError("switch this train to manual control before changing direction")
                coupled = self._coupled_trains(train_id)
                for member in coupled:
                    member_id = str(member["id"])
                    member_control = self.runtime.dispatcher.register_train(member_id)
                    motion = next((item for item in self.runtime.track.get_snapshot().trains if item.train_id == member_id), None)
                    if float(member.get("speed", 0)) > 0 or member_control.desired_speed > 0 or (motion and (motion.speed > 0 or motion.target_speed > 0)):
                        raise ValueError("stop the train and wait for it to halt before changing direction")
                for member in coupled:
                    member_id = str(member["id"])
                    result = self.runtime.track.set_train_direction(member_id, forward=direction == "forward")
                    if not result.accepted:
                        raise ValueError(result.detail or "direction command rejected")
                    member_control = self.runtime.dispatcher.register_train(member_id)
                    member_control.manual_speed = member_control.automatic_speed = 0.0
                    member["direction"] = direction
                self._record_action_if_active({"operation": "direction", "train_id": train_id, "direction": direction})
                self.events.append({"type": "train_direction_changed", "train_id": train_id, "direction": direction})
            elif kind in {"speed", "set_speed", "drive"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                if "direction" in payload and payload["direction"] != train.get("direction", "forward"):
                    raise ValueError("use set_direction while stopped to change direction")
                requested_speed = payload.get("speed", payload.get("speed_kmh", 0))
                requested_speed = float(requested_speed)
                if not math.isfinite(requested_speed) or requested_speed < 0:
                    raise ValueError("speed must be a finite non-negative number")
                maximum = max(1.0, float(train.get("maxSpeed", train.get("max_speed_kmh", 140))))
                requested_speed = min(maximum, requested_speed)
                if requested_speed > 0 and not self.track_power:
                    raise ValueError("switch track power on before requesting movement")
                coupled = self._coupled_trains(train_id)
                if self.runtime is not None:
                    control = self.runtime.dispatcher.register_train(train_id)
                    if requested_speed > 0 and control.mode is ControlMode.STOPPED:
                        # A stopped train is the safe startup state. An explicit
                        # speed request is the operator's instruction to resume
                        # it under manual control.
                        control.mode = ControlMode.MANUAL
                        train["mode"] = ControlMode.MANUAL.value
                    for member in coupled:
                        member_id = str(member["id"])
                        member_maximum = max(1.0, float(member.get("maxSpeed", member.get("max_speed_kmh", 140)) or 140))
                        member_speed = min(requested_speed, member_maximum)
                        member_control = self.runtime.dispatcher.register_train(member_id)
                        if member_speed > 0 and member_control.mode is ControlMode.STOPPED:
                            member_control.mode = ControlMode.MANUAL
                            member["mode"] = ControlMode.MANUAL.value
                        normalized = member_speed / member_maximum
                        command = self.runtime.dispatcher.automatic_speed if control.mode is ControlMode.AUTOMATIC else self.runtime.dispatcher.manual_speed
                        result = command(member_id, normalized)
                        if hasattr(result, "accepted") and not result.accepted:
                            raise ValueError(result.detail or "train speed command rejected")
                        member["speed"] = member["requested_speed_kmh"] = member_speed
                else:
                    for member in coupled:
                        member_maximum = max(1.0, float(member.get("maxSpeed", member.get("max_speed_kmh", 140)) or 140))
                        member["speed"] = member["requested_speed_kmh"] = min(requested_speed, member_maximum)
                train["speed"] = train["requested_speed_kmh"] = requested_speed
                self._publish_domain_event(
                    TrainSpeedChanged(
                        train_id=train_id,
                        speed_kmh=float(train["speed"]),
                        mode=TrainMode.AUTOMATIC if str(train.get("mode", "manual")).lower() == "automatic" else TrainMode.MANUAL,
                    )
                )
                self.events.append({"type": "train_command", "train_id": train_id, "speed": train["speed"]})
                self._record_action_if_active({"operation": "speed", "train_id": train_id, "speed": requested_speed / maximum})
            elif kind in {"stop_train", "stop"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                coupled = self._coupled_trains(train_id)
                if self.runtime is not None:
                    for member in coupled:
                        member_id = str(member["id"])
                        result = self.runtime.track.stop_train(member_id)
                        if hasattr(result, "accepted") and not result.accepted:
                            raise ValueError(result.detail or "train stop command rejected")
                        control = self.runtime.dispatcher.register_train(member_id)
                        control.manual_speed = control.automatic_speed = 0.0
                        control.last_command = "stop_train"
                for member in coupled:
                    member["speed"] = member["requested_speed_kmh"] = 0
                self.events.append({"type": "train_stopped", "train_id": train_id})
            elif kind in {"set_train_function", "set_decoder_function_state", "toggle_train_function"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                raw_number = payload.get("function_number", payload.get("number"))
                if isinstance(payload.get("function"), dict):
                    raw_number = payload["function"].get("function_number", payload["function"].get("number", raw_number))
                try:
                    function_number = int(raw_number)
                except (TypeError, ValueError) as exc:
                    raise ValueError("function number must be an integer") from exc
                if not 0 <= function_number <= 31:
                    raise ValueError("function number must be between 0 and 31")
                enabled = bool(payload.get("enabled", payload.get("active", payload.get("state", False))))
                if self.runtime is not None and hasattr(self.runtime.track, "set_train_function"):
                    result = self.runtime.track.set_train_function(train_id, function_number, enabled=enabled)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "decoder function command rejected")
                states = train.setdefault("decoder_function_states", {})
                states[str(function_number)] = enabled
                self._record_action_if_active({"operation": "function", "train_id": train_id, "function_number": function_number, "enabled": enabled})
                self.events.append({"type": "train_function_changed", "train_id": train_id, "function_number": function_number, "enabled": enabled})
            elif kind in {"track_power", "power"}:
                previous_power = self.track_power
                requested_power = bool(payload.get("enabled", payload.get("value", True)))
                if not requested_power and self.runtime is not None:
                    # Remove all train motion targets before dropping physical
                    # rail voltage.  This prevents a subsequent power restore
                    # from immediately re-energising an old command.
                    self.runtime.dispatcher.emergency_stop()
                if self.runtime is not None and hasattr(self.runtime.track, "set_power"):
                    result = self.runtime.track.set_power(requested_power)
                    if hasattr(result, "accepted") and not result.accepted:
                        self.track_power = previous_power
                        raise ValueError(result.detail or "track power command rejected")
                self.track_power = requested_power
                if not requested_power:
                    for train in self.trains:
                        train["mode"] = ControlMode.STOPPED.value
                        train["speed"] = 0
                    self._sync_ui_from_runtime()
                self._publish_domain_event(TrackPowerChanged(enabled=self.track_power))
                self.events.append({"type": "track_power", "enabled": self.track_power})
            elif kind in {"turnout", "set_turnout"}:
                turnout_id = str(payload.get("turnout_id", ""))
                turnout = next((item for item in self.turnouts if item["id"] == turnout_id), None)
                if turnout is None and turnout_id == "to1" and self.turnouts:
                    turnout = self.turnouts[0]
                if turnout is None:
                    raise ValueError(f"Unknown turnout: {turnout_id}")
                locked_by = self.runtime.interlocking.locks.get(str(turnout.get("id", "")).upper()) if self.runtime is not None and hasattr(self.runtime, "interlocking") else None
                if locked_by:
                    raise ValueError(f"turnout is locked by {locked_by}")
                turnout["state"] = str(payload.get("state", "straight"))
                if self.runtime is not None and hasattr(self.runtime.track, "set_turnout"):
                    result = self.runtime.track.set_turnout(turnout_id, 0 if turnout["state"] == "straight" else 1)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "turnout command rejected")
                elif self.runtime is not None and hasattr(self.runtime.track, "set_turnout_by_address"):
                    address = turnout.get("address")
                    if address in (None, ""):
                        raise ValueError("turnout has no DCC accessory address")
                    result = self.runtime.track.set_turnout_by_address(int(address), output=0 if turnout["state"] == "straight" else 1)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "turnout command rejected")
                self._publish_domain_event(
                    TurnoutPositionChanged(
                        turnout_id=str(turnout.get("id", turnout_id)),
                        position=TurnoutPosition.STRAIGHT if turnout["state"] == "straight" else TurnoutPosition.DIVERGING,
                    )
                )
                self.events.append({"type": "turnout_command", "turnout_id": turnout_id, "state": turnout["state"]})
            elif kind == "update_train":
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                updates = dict(payload.get("train", {}))
                allowed = {"name", "origin", "destination", "origin_block_id", "destination_block_id", "manufacturer", "model_number", "model", "era", "mass_g", "length_mm", "maxSpeed", "max_speed_kmh", "address", "decoder_protocol", "prototype"}
                train.update({key: value for key, value in updates.items() if key in allowed})
                for block_field in ("origin_block_id", "destination_block_id"):
                    if block_field in train and train[block_field] not in (None, ""):
                        train[block_field] = str(train[block_field]).strip().upper()
                if "number" in updates and str(updates["number"]).strip().isdigit():
                    train["address"] = int(updates["number"])
                self._sync_runtime_from_ui()
            elif kind in {"set_train_graph_membership", "set_train_graph", "toggle_train_graph"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                enabled = bool(payload.get("enabled", payload.get("on_graph", True)))
                if not enabled:
                    motion = next(
                        (item for item in self.runtime.track.get_snapshot().trains if item.train_id == train_id),
                        None,
                    ) if self.runtime is not None else None
                    control = self.runtime.dispatcher.trains.get(train_id) if self.runtime is not None else None
                    if (
                        float(train.get("speed", 0) or 0) > 0
                        or (control is not None and control.desired_speed > 0)
                        or (motion is not None and (motion.speed > 0 or motion.target_speed > 0))
                    ):
                        raise ValueError("stop the train before removing it from the node graph")
                    train["route"] = []
                    train["target_coordinate"] = None
                    train.update({
                        "mode": ControlMode.STOPPED.value,
                        "speed": 0,
                        "requested_speed_kmh": 0,
                    })
                train["graph_enabled"] = enabled
                self._sync_runtime_from_ui()
                self.events.append({
                    "type": "train_graph_membership_changed",
                    "train_id": train_id,
                    "enabled": enabled,
                })
            elif kind == "add_train":
                train = dict(payload.get("train", {}))
                train_id = str(train.get("id", "")).strip()
                if not train_id or any(item.get("id") == train_id for item in self.trains):
                    raise ValueError("train ID is required and must be unique")
                train.setdefault("name", "New service")
                train.setdefault("address", None)
                train.setdefault("mode", "manual")
                train.setdefault("speed", 0)
                train.setdefault("graph_enabled", True)
                train.setdefault("block_id", self.blocks[0]["id"] if self.blocks else "B01")
                train.setdefault("length_mm", 0)
                train.setdefault("maxSpeed", 120)
                train.setdefault("consist", [])
                self.trains.append(train)
                self._sync_runtime_from_ui()
                self.events.append({"type": "train_added", "train_id": train_id})
            elif kind == "update_consist":
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                raw_locomotive_ids = payload.get("locomotive_ids", train.get("locomotive_ids", ()))
                if not isinstance(raw_locomotive_ids, (list, tuple)):
                    raise ValueError("locomotive_ids must be a list")
                locomotive_ids: list[str] = []
                for raw_id in raw_locomotive_ids:
                    member_id = self._canonical_train_id(str(raw_id))
                    if member_id == train_id:
                        raise ValueError("a train cannot be paired with itself")
                    if not any(item["id"] == member_id for item in self.trains):
                        raise ValueError(f"Unknown locomotive: {raw_id}")
                    if member_id not in locomotive_ids:
                        locomotive_ids.append(member_id)
                previous_ids = set(train.get("locomotive_ids", ()))
                if "length_mm" in payload:
                    try:
                        length_mm = float(payload["length_mm"])
                    except (TypeError, ValueError) as exc:
                        raise ValueError("length_mm must be a finite non-negative number") from exc
                    if not math.isfinite(length_mm) or length_mm < 0:
                        raise ValueError("length_mm must be a finite non-negative number")
                    train["length_mm"] = length_mm
                train["consist"] = list(payload.get("consist", []))
                train["locomotive_ids"] = locomotive_ids
                for other in self.trains:
                    if other is train:
                        continue
                    other_ids = [str(item) for item in other.get("locomotive_ids", ()) if str(item) not in locomotive_ids]
                    if other_ids != list(other.get("locomotive_ids", ())):
                        other["locomotive_ids"] = other_ids
                for member_id in previous_ids - set(locomotive_ids):
                    member = next((item for item in self.trains if item["id"] == member_id), None)
                    if member is not None:
                        member.pop("coupled_to", None)
                for member_id in locomotive_ids:
                    member = next(item for item in self.trains if item["id"] == member_id)
                    member["coupled_to"] = train_id
                    member["block_id"] = train.get("block_id", member.get("block_id"))
                    member["route"] = list(train.get("route", member.get("route", [])))
                    member["direction"] = train.get("direction", member.get("direction", "forward"))
                    member["mode"] = train.get("mode", member.get("mode", "manual"))
                    member["speed"] = member["requested_speed_kmh"] = min(
                        float(train.get("speed", 0) or 0),
                        float(member.get("maxSpeed", member.get("max_speed_kmh", 140)) or 140),
                    )
                self._sync_runtime_from_ui()
            elif kind in {"update_decoder_function", "upsert_decoder_function", "set_decoder_function"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None or self.runtime is None:
                    raise ValueError(f"Unknown train: {train_id}")
                raw_mapping = payload.get("function", payload.get("mapping", {}))
                if not isinstance(raw_mapping, dict):
                    raw_mapping = {}
                raw_number = raw_mapping.get("function_number", raw_mapping.get("number", payload.get("function_number", payload.get("number", 0))))
                try:
                    function_number = int(raw_number)
                except (TypeError, ValueError) as exc:
                    raise ValueError("decoder function number must be an integer") from exc
                mapping = DecoderFunctionMapping(
                    train_id=train_id,
                    function_number=function_number,
                    name=str(raw_mapping.get("name", raw_mapping.get("function_name", payload.get("name", "")))).strip(),
                    description=str(raw_mapping.get("description", payload.get("description", ""))),
                    momentary=bool(raw_mapping.get("momentary", payload.get("momentary", False))),
                    enabled=bool(raw_mapping.get("enabled", payload.get("enabled", True))),
                    metadata=dict(raw_mapping.get("metadata", payload.get("metadata", {})) or {}),
                )
                self.runtime.train_database.upsert_decoder_function(mapping)
                raw_functions = train.get("decoder_functions", {})
                if not isinstance(raw_functions, dict):
                    raw_functions = {
                        str(item.get("function_number", index)): item
                        for index, item in enumerate(raw_functions if isinstance(raw_functions, (list, tuple)) else ())
                        if isinstance(item, dict)
                    }
                raw_functions[str(function_number)] = {
                    "function_number": function_number,
                    "name": mapping.name,
                    "description": mapping.description,
                    "momentary": mapping.momentary,
                    "enabled": mapping.enabled,
                    "metadata": dict(mapping.metadata),
                }
                train["decoder_functions"] = raw_functions
                self._publish_domain_event(TrainDatabaseChanged(train_id=train_id, entity="decoder_function", action="updated", record_id=str(function_number)))
                self.events.append({"type": "decoder_function_updated", "train_id": train_id, "function_number": function_number})
            elif kind in {"delete_decoder_function", "remove_decoder_function"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None or self.runtime is None:
                    raise ValueError(f"Unknown train: {train_id}")
                raw_number = payload.get("function_number", payload.get("number"))
                if isinstance(payload.get("function"), dict):
                    raw_number = payload["function"].get("function_number", payload["function"].get("number", raw_number))
                try:
                    function_number = int(raw_number)
                except (TypeError, ValueError) as exc:
                    raise ValueError("decoder function number must be an integer") from exc
                if not self.runtime.train_database.delete_decoder_function(train_id, function_number):
                    raise ValueError(f"Unknown decoder function: F{function_number}")
                raw_functions = train.get("decoder_functions", {})
                if isinstance(raw_functions, dict):
                    raw_functions.pop(str(function_number), None)
                    raw_functions.pop(function_number, None)
                elif isinstance(raw_functions, list):
                    train["decoder_functions"] = [
                        item for item in raw_functions
                        if not isinstance(item, dict) or int(item.get("function_number", -1)) != function_number
                    ]
                self._publish_domain_event(TrainDatabaseChanged(train_id=train_id, entity="decoder_function", action="deleted", record_id=str(function_number)))
                self.events.append({"type": "decoder_function_deleted", "train_id": train_id, "function_number": function_number})
            elif kind in {"add_maintenance", "upsert_maintenance", "update_maintenance", "maintenance"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None or self.runtime is None:
                    raise ValueError(f"Unknown train: {train_id}")
                raw_record = payload.get("maintenance", payload.get("record", {}))
                if not isinstance(raw_record, dict):
                    raw_record = {}

                def optional_float(value: Any) -> float | None:
                    if value in (None, ""):
                        return None
                    return float(value)

                raw_record_id = raw_record.get("record_id", raw_record.get("id", payload.get("record_id")))
                record_id = int(raw_record_id) if raw_record_id not in (None, "") else None
                record = MaintenanceRecord(
                    train_id=train_id,
                    service_date=str(raw_record.get("service_date", raw_record.get("date", payload.get("service_date", "")))).strip(),
                    service_type=str(raw_record.get("service_type", raw_record.get("type", payload.get("service_type", "")))).strip(),
                    description=str(raw_record.get("description", payload.get("description", ""))),
                    mileage_km=optional_float(raw_record.get("mileage_km", payload.get("mileage_km"))),
                    cost=optional_float(raw_record.get("cost", payload.get("cost"))),
                    performed_by=str(raw_record.get("performed_by", payload.get("performed_by", ""))),
                    next_service_date=(
                        str(next_service_date_value).strip() or None
                        if (next_service_date_value := raw_record.get("next_service_date", payload.get("next_service_date"))) not in (None, "")
                        else None
                    ),
                    record_id=record_id,
                    metadata=dict(raw_record.get("metadata", payload.get("metadata", {})) or {}),
                )
                saved = self.runtime.train_database.upsert_maintenance_record(record)
                self._publish_domain_event(TrainDatabaseChanged(train_id=train_id, entity="maintenance", action="updated" if record_id is not None else "created", record_id=str(saved.record_id) if saved.record_id is not None else None))
                self.events.append({"type": "maintenance_updated", "train_id": train_id, "record_id": saved.record_id})
            elif kind in {"delete_maintenance", "remove_maintenance"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                if self.runtime is None or not any(item["id"] == train_id for item in self.trains):
                    raise ValueError(f"Unknown train: {train_id}")
                raw_record_id = payload.get("record_id", payload.get("maintenance_id"))
                if isinstance(payload.get("maintenance"), dict):
                    raw_record_id = payload["maintenance"].get("record_id", payload["maintenance"].get("id", raw_record_id))
                try:
                    record_id = int(raw_record_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("maintenance record ID must be an integer") from exc
                record = self.runtime.train_database.get_maintenance_record(record_id)
                if record is None or record.train_id != train_id or not self.runtime.train_database.delete_maintenance_record(record_id):
                    raise ValueError(f"Unknown maintenance record: {record_id}")
                self._publish_domain_event(TrainDatabaseChanged(train_id=train_id, entity="maintenance", action="deleted", record_id=str(record_id)))
                self.events.append({"type": "maintenance_deleted", "train_id": train_id, "record_id": record_id})
            elif kind in {"set_signal", "signal"}:
                signal_id = str(payload.get("signal_id", payload.get("id", ""))).strip().upper()
                signal = next((item for item in self.signals if str(item.get("id", "")).upper() == signal_id), None)
                if signal is None:
                    raise ValueError(f"Unknown signal: {signal_id}")
                signal["aspect"] = str(payload.get("aspect", "red")).lower()
                if self.runtime is not None and hasattr(self.runtime.track, "set_turnout_by_address") and signal.get("address") not in (None, ""):
                    result = self.runtime.track.set_turnout_by_address(int(signal["address"]), output=0 if signal["aspect"] == "red" else 1)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "signal command rejected")
                self._publish_domain_event(
                    SignalAspectChanged(
                        signal_id=str(signal.get("id", signal_id)),
                        aspect=SignalAspect(signal["aspect"]),
                    )
                )
                self.events.append({"type": "signal_command", "signal_id": signal_id, "aspect": signal["aspect"]})
            elif kind in {"align_turntable", "turntable"}:
                turntable_id = str(payload.get("turntable_id", payload.get("id", ""))).strip().upper()
                turntable = next((item for item in self.turntables if str(item.get("id", "")).upper() == turntable_id), None)
                if turntable is None:
                    raise ValueError(f"Unknown turntable: {turntable_id}")
                turntable["aligned_block_id"] = str(payload.get("block_id", "")).strip().upper()
                if self.runtime is not None and hasattr(self.runtime.track, "set_turnout_by_address") and turntable.get("address") not in (None, ""):
                    result = self.runtime.track.set_turnout_by_address(int(turntable["address"]), output=0 if turntable["aligned_block_id"] == str(turntable.get("connected_block_ids", [""])[0]).upper() else 1)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "turntable command rejected")
                self.events.append({"type": "turntable_aligned", "turntable_id": turntable_id, "block_id": turntable["aligned_block_id"]})
            elif kind in {"poll_feedback", "feedback_poll"}:
                if self.runtime is None or not hasattr(self.runtime.track, "poll_feedback"):
                    raise ValueError("the active track system has no R-BUS feedback poller")
                groups = payload.get("groups", [0])
                results = self.runtime.track.poll_feedback(groups)
                self.feedback_occupancy = {str(block_id): tuple(values) for block_id, values in self.runtime.track.get_snapshot().occupied_blocks.items()}
                for block_id, occupants in self.feedback_occupancy.items():
                    self._publish_domain_event(
                        BlockStateChanged(
                            block_id=str(block_id),
                            state=BlockState.OCCUPIED if occupants else BlockState.FREE,
                            occupied_by=str(occupants[0]) if occupants else None,
                        )
                    )
                self._publish_domain_event(
                    FeedbackHealthChanged(
                        healthy=bool(getattr(self.runtime.track, "feedback_healthy", True)),
                        error=str(getattr(self.runtime.track, "feedback_error", "")),
                    )
                )
                self.events.append({"type": "feedback_polled", "groups": list(groups), "accepted": all(result.accepted for result in results)})
            elif kind == "add_block":
                block = dict(payload.get("block", {}))
                block_id = validate_block_id(block["id"] if "id" in block else next_block_id(self.blocks))
                if any(str(item.get("id", "")).upper() == block_id for item in self.blocks):
                    raise ValueError("block ID is required and must be unique")
                block["id"] = block_id
                block.setdefault("name", block_id)
                block.setdefault("x", 62)
                block.setdefault("y", 224)
                block.setdefault("status", "free")
                self.blocks.append(block)
                self._sync_runtime_from_ui(apply_motion=False)
                self.events.append({"type": "block_added", "block_id": block_id})
            elif kind in {"remove_block", "delete_block"}:
                block_id = str(payload.get("block_id", payload.get("id", ""))).strip().upper()
                block_index = next((index for index, item in enumerate(self.blocks)
                                    if str(item.get("id", "")).upper() == block_id), None)
                if block_index is None:
                    raise ValueError(f"Unknown block: {block_id}")
                block = self.blocks[block_index]
                status = str(block.get("status", "free")).strip().lower()
                if status in {"occupied", "route", "reserved", "out_of_service", "offline"} or block.get("occupied_by") or block.get("reserved_for"):
                    raise ValueError(f"cannot remove block {block_id} while it is in use")

                def references(collection: Iterable[dict[str, Any]], fields: Iterable[str]) -> list[str]:
                    matches = []
                    for item in collection:
                        for field in fields:
                            value = item.get(field)
                            values = value if isinstance(value, (list, tuple, set)) else (value,)
                            if any(str(candidate).strip().upper() == block_id for candidate in values if candidate not in (None, "")):
                                matches.append(str(item.get("id", "")))
                                break
                    return matches

                runtime_occupants = ()
                if self.runtime is not None and hasattr(self.runtime.track, "get_snapshot"):
                    runtime_occupants = tuple(
                        motion.train_id for motion in self.runtime.track.get_snapshot().trains
                        if str(motion.block_id).upper() == block_id
                    )
                if runtime_occupants:
                    raise ValueError(f"cannot remove block {block_id} while a train is occupying it")
                train_refs = references(self.trains, ("block_id", "destination_block_id", "current_block_id"))
                if train_refs:
                    raise ValueError(f"cannot remove block {block_id}: train {train_refs[0]} references it")
                for label, collection, fields in (
                    ("turnout", self.turnouts, ("from", "to", "alternate", "entry_block_id", "straight_block_id", "diverging_block_id")),
                    ("station", self.stations, ("blockIds", "block_ids")),
                    ("signal", self.signals, ("block_id", "protects_block_id")),
                    ("waypoint", self.waypoints, ("connected_node_ids", "connectedNodeIds")),
                    ("turntable", self.turntables, ("connected_block_ids", "aligned_block_id")),
                    ("platform", self.platforms, ("blockId", "block_id")),
                    ("route", self.routes, ("source_block_id", "target_block_id", "node_ids", "path")),
                    ("connection speed limit", self.connection_limits, ("from", "to", "from_block_id", "to_block_id")),
                ):
                    matches = references(collection, fields)
                    if matches:
                        raise ValueError(f"cannot remove block {block_id}: {label} {matches[0]} references it")

                self.blocks.pop(block_index)
                for other in self.blocks:
                    neighbours = other.get("neighbor_ids", other.get("neighborIds"))
                    if neighbours is None:
                        continue
                    filtered = [item for item in neighbours if str(item).strip().upper() != block_id]
                    other["neighbor_ids"] = filtered
                    other.pop("neighborIds", None)
                self.connection_limits = [rule for rule in self.connection_limits
                                          if str(rule.get("from", "")).upper() != block_id
                                          and str(rule.get("to", "")).upper() != block_id]
                self._sync_runtime_from_ui(apply_motion=False)
                self.events.append({"type": "block_removed", "block_id": block_id})
            elif kind == "update_block":
                block_id = str(payload.get("block_id", payload.get("id", ""))).strip().upper()
                block = next((item for item in self.blocks if str(item.get("id", "")).upper() == block_id), None)
                if block is None:
                    raise ValueError(f"Unknown block: {block_id}")
                updates = dict(payload.get("block", {}))
                if "length_mm" in updates:
                    length = float(updates["length_mm"])
                    if not math.isfinite(length) or length < 0:
                        raise ValueError("Block length must be a finite non-negative number")
                new_id = validate_block_id(updates.get("id", block_id))
                if new_id != block_id:
                    if self.track_power:
                        raise ValueError("Switch track power off before renaming a block ID")
                    if any(str(item["id"]).upper() == new_id for item in self.blocks):
                        raise ValueError("Block ID already exists")
                    collections = ("blocks", "turnouts", "trains", "stations", "signals",
                                   "waypoints", "turntables", "platforms", "schedules", "routes", "scans", "connection_limits")
                    updated = {key: rename_references(getattr(self, key), block_id, new_id)
                               for key in collections}
                    for item in updated["blocks"]:
                        if str(item["id"]).upper() == block_id:
                            item["id"] = new_id
                    snapshot_from_ui(**updated, edges=rename_references(self._topology_edges(), block_id, new_id))
                    self.runtime.track.rename_block(block_id, new_id)
                    for key, value in updated.items():
                        setattr(self, key, value)
                    self.feedback_map = {key: new_id if str(value).upper() == block_id else value for key, value in self.feedback_map.items()}
                    self.feedback_occupancy = {new_id if key.upper() == block_id else key: value for key, value in self.feedback_occupancy.items()}
                    self._last_train_blocks = {key: new_id if value.upper() == block_id else value for key, value in self._last_train_blocks.items()}
                    for train_id, route in self.runtime.route_updater.desired_routes.items():
                        self.runtime.route_updater.set_route(train_id, tuple(new_id if item.upper() == block_id else item for item in route))
                    block_id = new_id
                    block = next(item for item in self.blocks if item["id"] == new_id)
                if "name" in updates:
                    block["name"] = str(updates["name"]).strip() or block_id
                if "length_mm" in updates:
                    block["length_mm"] = max(0, float(updates["length_mm"]))
                if "station" in updates:
                    block["station"] = str(updates["station"]).strip()
                self._sync_runtime_from_ui(apply_motion=False)
                raw_state = str(block.get("status", "free")).lower()
                block_state = BlockState.OCCUPIED if raw_state == "occupied" else BlockState.RESERVED if raw_state in {"route", "reserved"} else BlockState.OUT_OF_SERVICE if raw_state in {"out_of_service", "offline"} else BlockState.FREE
                self._publish_domain_event(BlockStateChanged(block_id=block_id, state=block_state, occupied_by=block.get("occupied_by")))
                self.events.append({"type": "block_updated", "block_id": block_id})
            elif kind in {"connect_blocks", "connect"}:
                left_id = str(payload.get("from_block_id", payload.get("from", ""))).strip().upper()
                right_id = str(payload.get("to_block_id", payload.get("to", ""))).strip().upper()
                if not left_id or not right_id or left_id == right_id:
                    raise ValueError("two distinct block IDs are required")
                left = next((item for item in self.blocks if str(item.get("id", "")).upper() == left_id), None)
                right = next((item for item in self.blocks if str(item.get("id", "")).upper() == right_id), None)
                if left is None or right is None:
                    raise ValueError("both blocks must exist before connecting them")
                for block, other_id in ((left, right_id), (right, left_id)):
                    neighbours = {str(item).strip().upper() for item in block.get("neighbor_ids", block.get("neighborIds", ())) if str(item).strip()}
                    neighbours.add(other_id)
                    block["neighbor_ids"] = sorted(neighbours)
                    block.pop("neighborIds", None)
                self._sync_runtime_from_ui()
                self.events.append({"type": "blocks_connected", "from": left_id, "to": right_id})
            elif kind in {"disconnect_blocks", "disconnect"}:
                left_id = str(payload.get("from_block_id", payload.get("from", ""))).strip().upper()
                right_id = str(payload.get("to_block_id", payload.get("to", ""))).strip().upper()
                left = next((item for item in self.blocks if str(item.get("id", "")).upper() == left_id), None)
                right = next((item for item in self.blocks if str(item.get("id", "")).upper() == right_id), None)
                if left is None or right is None:
                    raise ValueError("both blocks must exist before disconnecting them")
                for block, other_id in ((left, right_id), (right, left_id)):
                    neighbours = {str(item).strip().upper() for item in block.get("neighbor_ids", block.get("neighborIds", ())) if str(item).strip()}
                    neighbours.discard(other_id)
                    block["neighbor_ids"] = sorted(neighbours)
                    block.pop("neighborIds", None)
                self.connection_limits = [rule for rule in self.connection_limits
                    if {rule["from"], rule["to"]} != {left_id, right_id}]
                self._sync_runtime_from_ui()
                self.events.append({"type": "blocks_disconnected", "from": left_id, "to": right_id})
            elif self._command_layout_asset(kind, payload):
                pass
            elif kind in {"add_scan", "update_scan"}:
                scan = dict(payload.get("scan", {}))
                scan_id = str(scan.get("id", "")).strip()
                if not scan_id:
                    raise ValueError("scan ID is required")
                existing = next((item for item in self.scans if str(item.get("id", "")) == scan_id), None)
                if kind == "add_scan" and existing is not None:
                    raise ValueError("scan ID must be unique")
                if existing is None:
                    scan.setdefault("label", scan_id)
                    scan.setdefault("description", "")
                    scan.setdefault("image", None)
                    scan.setdefault("anchor", {"x": 0.5, "y": 0.5})
                    self.scans.append(scan)
                else:
                    existing.update(scan)
                self._persist_scan_manifest()
                self.events.append({"type": "scan_updated", "scan_id": scan_id})
            elif kind == "remove_scan":
                scan_id = str(payload.get("scan_id", "")).strip()
                before = len(self.scans)
                self.scans = [item for item in self.scans if str(item.get("id", "")) != scan_id]
                if len(self.scans) == before:
                    raise ValueError(f"Unknown scan: {scan_id}")
                self._persist_scan_manifest()
                self.events.append({"type": "scan_removed", "scan_id": scan_id})
            elif kind == "move_block":
                block_id = str(payload.get("block_id", "")).strip().upper()
                block = next((item for item in self.blocks if str(item.get("id", "")).upper() == block_id), None)
                if block is None:
                    raise ValueError(f"Unknown block: {block_id}")
                block["x"] = max(0, int(payload.get("x", block.get("x", 0))))
                block["y"] = max(0, int(payload.get("y", block.get("y", 0))))
                self._sync_runtime_from_ui()
                self.events.append({"type": "block_moved", "block_id": block_id, "x": block["x"], "y": block["y"]})
            elif kind == "add_route":
                route = dict(payload.get("route", {}))
                route_id = str(route.get("id", "")).strip()
                if not route_id or any(item.get("id") == route_id for item in self.routes):
                    raise ValueError("route ID is required and must be unique")
                flow, flow_nodes = self._normalize_route_flow(route.get("flow")) if "flow" in route else ([], [])
                source = str(route.get("source_block_id") or route.get("source") or (flow_nodes[0] if flow_nodes else "")).strip().upper()
                target = str(route.get("target_block_id") or route.get("target") or (flow_nodes[-1] if flow_nodes else "")).strip().upper()
                requested = route.get("node_ids") or route.get("path") or (flow_nodes if flow_nodes else None)
                if source or target or requested:
                    path, algorithm = self._route_path(source, target, route.get("algorithm", "a_star"), requested)
                else:
                    if not flow:
                        raise ValueError("route must contain at least one flow block")
                    path, algorithm = [], "stationary"
                saved = {"id": route_id, "name": str(route.get("name", route_id)).strip() or route_id,
                         "source_block_id": source or None, "target_block_id": target or None, "node_ids": path,
                         "algorithm": algorithm, "enabled": bool(route.get("enabled", True))}
                if "flow" in route:
                    saved["flow"] = flow
                self.routes.append(saved)
                self._sync_runtime_from_ui()
                self.events.append({"type": "route_added", "route_id": route_id, "route": deepcopy(saved)})
            elif kind == "update_route":
                route_id = str(payload.get("route_id", payload.get("id", ""))).strip()
                route = next((item for item in self.routes if item.get("id") == route_id), None)
                if route is None:
                    raise ValueError(f"Unknown route: {route_id}")
                updates = dict(payload.get("route", {}))
                flow_present = "flow" in updates
                flow, flow_nodes = self._normalize_route_flow(updates.get("flow")) if flow_present else (list(route.get("flow", [])), [str(item).upper() for item in route.get("node_ids", ())])
                source = str(updates.get("source_block_id") or updates.get("source") or (flow_nodes[0] if flow_nodes else route.get("source_block_id", "")) or "").strip().upper()
                target = str(updates.get("target_block_id") or updates.get("target") or (flow_nodes[-1] if flow_nodes else route.get("target_block_id", "")) or "").strip().upper()
                path_requested = updates.get("node_ids") or updates.get("path") or (flow_nodes if flow_nodes else None)
                if source or target or path_requested:
                    path, algorithm = self._route_path(source, target, updates.get("algorithm", route.get("algorithm", "a_star")), path_requested)
                else:
                    if flow_present and not flow:
                        raise ValueError("route must contain at least one flow block")
                    path, algorithm = [], "stationary"
                route.update({"name": str(updates.get("name", route.get("name", route_id))).strip() or route_id,
                              "source_block_id": source or None, "target_block_id": target or None, "node_ids": path,
                              "algorithm": algorithm, "enabled": bool(updates.get("enabled", route.get("enabled", True)))})
                if flow_present:
                    route["flow"] = flow
                self._sync_runtime_from_ui()
                self.events.append({"type": "route_updated", "route_id": route_id, "route": deepcopy(route)})
            elif kind == "remove_route":
                route_id = str(payload.get("route_id", payload.get("id", ""))).strip()
                before = len(self.routes)
                self.routes = [item for item in self.routes if item.get("id") != route_id]
                if len(self.routes) == before:
                    raise ValueError(f"Unknown route: {route_id}")
                self._sync_runtime_from_ui()
                self.events.append({"type": "route_removed", "route_id": route_id})
            elif kind == "apply_route":
                route_id = str(payload.get("route_id", "")).strip()
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                route = next((item for item in self.routes if item.get("id") == route_id), None)
                train = next((item for item in self.trains if item.get("id") == train_id), None)
                if route is None or train is None or self.runtime is None:
                    raise ValueError("known route, train, and runtime are required")
                if not route.get("enabled", True):
                    raise ValueError("cannot apply a disabled route")
                path = tuple(str(item).upper() for item in route.get("node_ids", ()))
                if not path:
                    raise ValueError("stationary routes are reusable definitions and cannot be bound to a train yet")
                self.runtime.route_updater.set_route(train_id, path)
                if hasattr(self.runtime.track, "set_train_route"):
                    self.runtime.track.set_train_route(train_id, path)
                train["destination_block_id"] = path[-1]
                train["route"] = list(path)
                self._publish_domain_event(RouteChanged(train_id=train_id, route=path))
                self.events.append({"type": "route_applied", "route_id": route_id, "train_id": train_id, "route": list(path)})
            elif kind == "add_schedule":
                schedule = dict(payload.get("schedule", {}))
                schedule_id = str(schedule.get("id", "")).strip()
                if not schedule_id or any(item.get("id") == schedule_id for item in self.schedules):
                    raise ValueError("schedule ID is required and must be unique")
                schedule.setdefault("time", "11:15")
                schedule.setdefault("service", "New service")
                schedule.setdefault("number", "NEW")
                schedule.setdefault("state", "Draft")
                self._validate_schedule_dispatch(schedule)
                self._validate_schedule_coordinate(schedule)
                self.schedules.append(schedule)
                self._sync_runtime_from_ui()
                self._publish_domain_event(
                    ScheduleStateChanged(
                        schedule_id=schedule_id,
                        status=self._schedule_domain_status(schedule.get("state")),
                    )
                )
                self.events.append({"type": "schedule_added", "schedule_id": schedule_id})
            elif kind == "update_schedule":
                schedule_id = str(payload.get("schedule_id", "")).strip()
                schedule = next((item for item in self.schedules if item.get("id") == schedule_id), None)
                if schedule is None:
                    raise ValueError(f"Unknown schedule: {schedule_id}")
                updates = dict(payload.get("schedule", {}))
                candidate = {**schedule, **updates}
                self._validate_schedule_dispatch(candidate)
                updates["dispatch_mode"] = candidate["dispatch_mode"]
                updates["route_id"] = candidate.get("route_id")
                updates["destination_coordinate"] = candidate.get("destination_coordinate")
                self._validate_schedule_coordinate(updates)
                schedule.update(updates)
                self._sync_runtime_from_ui()
                self._publish_domain_event(
                    ScheduleStateChanged(
                        schedule_id=schedule_id,
                        status=self._schedule_domain_status(schedule.get("state")),
                    )
                )
                self.events.append({"type": "schedule_updated", "schedule_id": schedule_id})
            elif kind == "remove_schedule":
                schedule_id = str(payload.get("schedule_id", "")).strip()
                before = len(self.schedules)
                self.schedules = [item for item in self.schedules if item.get("id") != schedule_id]
                if len(self.schedules) == before:
                    raise ValueError(f"Unknown schedule: {schedule_id}")
                self._sync_runtime_from_ui()
                self._publish_domain_event(ScheduleStateChanged(schedule_id=schedule_id, status=ScheduleStatus.CANCELLED))
                self.events.append({"type": "schedule_removed", "schedule_id": schedule_id})
            elif kind == "simulate_schedule":
                if self.runtime is None:
                    raise ValueError("runtime is not available")
                current_tick = self.runtime.scheduler.world_current_tick
                if "until_tick" in payload:
                    until_tick = int(payload["until_tick"])
                else:
                    future_ticks = [
                        tick
                        for stop in self.runtime.scheduler.stops
                        for tick in (stop.arrival_tick, stop.departure_tick)
                        if tick > current_tick
                    ]
                    until_tick = min(future_ticks) if future_ticks else current_tick + 1
                schedule_events = self.runtime.scheduler.simulate_world(until_tick) if self.runtime is not None else ()
                self.runtime.scheduler.current_tick = until_tick
                self._world_clock_seconds = max(self._world_clock_seconds, until_tick * 60)
                for schedule_event in schedule_events:
                    state = "Arrived" if schedule_event.kind.value == "arrival" else "Departed"
                    schedule_id = str(schedule_event.stop.stop_id).split("#", 1)[0]
                    row = next((item for item in self.schedules if item.get("id") == schedule_id), None)
                    if row is not None:
                        row["state"] = state
                        if schedule_event.kind.value == "departure":
                            self._schedule_coordinate_target(row, schedule_event.stop.stop_id, schedule_event.stop.train_id)
                    self._publish_domain_event(
                        ScheduleStateChanged(
                            schedule_id=schedule_id,
                            status=ScheduleStatus.COMPLETED if state == "Arrived" else ScheduleStatus.ACTIVE,
                        )
                    )
                    self.events.append({"type": f"schedule_{schedule_event.kind.value}", "schedule_id": schedule_id, "stop_id": schedule_event.stop.stop_id, "train_id": schedule_event.stop.train_id, "tick": schedule_event.tick})
                self.events.append({"type": "schedule_simulated", "from_tick": current_tick, "until_tick": until_tick, "events": len(schedule_events)})
            elif kind == "save_layout":
                self.save_layout(str(payload.get("layout_id", self.layout_id)), name=payload.get("name"))
            elif kind in {"set_train_mode", "switch_train_mode"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                requested_mode = str(payload.get("mode", "manual")).strip().lower()
                selected_mode = ControlMode.STOPPED if requested_mode in {"stopped", "stop", "safe"} else ControlMode(requested_mode)
                train["mode"] = selected_mode.value
                if selected_mode is ControlMode.STOPPED:
                    train["speed"] = train["requested_speed_kmh"] = 0
                if self.runtime is not None:
                    result = self.runtime.mode_switcher.switch(train_id, selected_mode)
                    if not result.accepted:
                        raise ValueError(f"train mode change rejected: {train_id}")
                    self._sync_runtime_from_ui()
                self._publish_domain_event(
                    TrainModeChanged(
                        train_id=train_id,
                        mode=TrainMode.MANUAL if selected_mode is ControlMode.MANUAL else TrainMode.AUTOMATIC if selected_mode is ControlMode.AUTOMATIC else TrainMode.STOPPED,
                    )
                )
                self.events.append({"type": "train_mode_changed", "train_id": train_id, "mode": selected_mode.value})
            elif kind in {"set_mode", "pause_simulation", "resume_simulation", "plan_route"}:
                if kind == "pause_simulation":
                    self.simulation_running = False
                    if self.runtime is not None:
                        self.runtime.scheduler.pause()
                elif kind == "resume_simulation":
                    self.simulation_running = True
                    if self.runtime is not None:
                        self.runtime.scheduler.start()
                elif kind == "set_mode" and self.runtime is not None:
                    requested_mode = str(payload.get("mode", "manual")).lower()
                    selected_mode = ControlMode.STOPPED if requested_mode in {"stopped", "stop"} else ControlMode(requested_mode)
                    for train in self.trains:
                        train["mode"] = selected_mode.value
                        if selected_mode is ControlMode.STOPPED:
                            train["speed"] = train["requested_speed_kmh"] = 0
                        self.runtime.mode_switcher.switch(train["id"], selected_mode)
                        self._publish_domain_event(
                            TrainModeChanged(
                                train_id=str(train["id"]),
                                mode=TrainMode.MANUAL if selected_mode is ControlMode.MANUAL else TrainMode.AUTOMATIC if selected_mode is ControlMode.AUTOMATIC else TrainMode.STOPPED,
                            )
                        )
                elif kind == "plan_route":
                    train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                    train = next((item for item in self.trains if item["id"] == train_id), None)
                    if train is None or self.runtime is None:
                        raise ValueError(f"Unknown train: {train_id}")
                    graph = self.runtime.layout.graph()
                    start_id = str(train.get("block_id", "")).upper()
                    requested_goal = str(payload.get("destination_block_id", payload.get("destination", ""))).upper()
                    block_goal = next((block.id for block in reversed(self.runtime.layout.snapshot().snapshot.blocks) if graph.node(block.id) is not None), start_id)
                    goal_id = requested_goal if graph.node(requested_goal) is not None else block_goal
                    route = find_route(graph, start_id, goal_id, algorithm=RouteAlgorithm.A_STAR) if graph.node(start_id) is not None else None
                    if route is None:
                        route = find_route(graph, start_id, goal_id, algorithm=RouteAlgorithm.BFS) if graph.node(start_id) is not None else None
                    if route is None:
                        raise ValueError(f"No route from {start_id} to {goal_id}")
                    self.runtime.route_updater.set_route(train_id, route.node_ids)
                    if hasattr(self.runtime.track, "set_train_route"):
                        self.runtime.track.set_train_route(train_id, route.node_ids)
                    train["destination_block_id"] = goal_id
                    train["route"] = list(route.node_ids)
                    self._publish_domain_event(RouteChanged(train_id=train_id, route=tuple(route.node_ids)))
                    self.events.append({"type": "route_planned", "train_id": train_id, "algorithm": route.algorithm.value, "route": list(route.node_ids), "cost": route.cost})
                self.events.append({"type": kind, "payload": payload})
            elif kind in {"mode", "simulation_mode"}:
                self.simulation_mode = bool(payload.get("enabled", True))
            else:
                raise ValueError(f"Unsupported command: {kind or 'missing type'}")
            self._routing_wake.set()
            return self._ui_snapshot()


class ControllerHandler(BaseHTTPRequestHandler):
    """JSON API and static frontend handler."""

    application: ControllerApplication

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, *, max_bytes: int = 1_000_000) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > max_bytes:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings":
            return self._send_json(self.application.settings_payload())
        if parsed.path.startswith("/api/scans/files/"):
            return self._send_scan_file(unquote(parsed.path.removeprefix("/api/scans/files/")))
        if parsed.path == "/api/state":
            return self._send_json(self.application.state())
        if parsed.path == "/api/layout":
            snapshot = self.application.state()
            return self._send_json(snapshot["layout"])
        if parsed.path == "/api/trains":
            return self._send_json({"trains": self.application.state()["trains"]})
        if parsed.path == "/api/train-database":
            return self._send_json({"trains": self.application.train_database()})
        if parsed.path == "/api/calibration":
            return self._send_json(self.application.calibration_state())
        if parsed.path == "/api/presence":
            return self._send_json(self.application.train_presence_state())
        if parsed.path == "/api/rolling-stock":
            return self._send_json(self.application.rolling_stock_inventory())
        if parsed.path == "/api/programming":
            return self._send_json(self.application.programming_state())
        if parsed.path == "/api/train-catalogue":
            query = parse_qs(parsed.query)
            format_name = query.get("format", ["json"])[0]
            try:
                return self._send_json(self.application.train_catalogue(format_name))
            except ValueError as exc:
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path.startswith("/api/train-database/"):
            train_id = self.application._canonical_train_id(parsed.path.removeprefix("/api/train-database/").strip())
            record = self.application.train_database(train_id)
            if record is None:
                return self._send_json({"error": "train model not found"}, HTTPStatus.NOT_FOUND)
            return self._send_json(record)
        if parsed.path == "/api/connection":
            self.application.check_connection()
            snapshot = self.application.state()
            return self._send_json(snapshot["connection"])
        if parsed.path == "/api/events":
            return self._send_json({"events": self.application.state()["events"]})
        if parsed.path == "/api/feedback":
            snapshot = self.application.state()
            return self._send_json({"occupied_blocks": self.application.feedback_occupancy, **snapshot.get("feedback", {})})
        if parsed.path == "/api/scans":
            return self._send_json({"scans": self.application.state()["scans"]})
        if parsed.path == "/api/layouts":
            records = self.application.runtime.layout_repository.list() if self.application.runtime is not None else ()
            return self._send_json({"layouts": [record.__dict__ for record in records]})
        if parsed.path.startswith("/api/layouts/"):
            layout_id = parsed.path.removeprefix("/api/layouts/").strip()
            if not layout_id:
                return self._send_json({"error": "layout ID is required"}, HTTPStatus.BAD_REQUEST)
            if self.application.runtime is None:
                return self._send_json({"error": "runtime is not available"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            snapshot = self.application.runtime.layout_repository.load(layout_id)
            if snapshot is None:
                return self._send_json({"error": "layout not found"}, HTTPStatus.NOT_FOUND)
            return self._send_json({"layout_id": layout_id, "layout": snapshot_to_ui(snapshot)})
        return self._send_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/settings":
                return self._send_json(self.application.update_settings(self._read_json()))
            if parsed.path == "/api/scans/upload":
                return self._send_json(self.application.upload_scan(self._read_json(max_bytes=MAX_UPLOAD_BODY_BYTES)), HTTPStatus.CREATED)
            if parsed.path == "/api/commands":
                return self._send_json(self.application.command(self._read_json()))
            if parsed.path == "/api/train-catalogue":
                payload = self._read_json()
                content = payload.get("content", payload.get("catalogue", payload.get("trains")))
                if content is None:
                    raise ValueError("catalogue content is required")
                result = self.application.import_train_catalogue(
                    content,
                    format_name=str(payload.get("format", "json")),
                    on_conflict=str(payload.get("on_conflict", payload.get("onConflict", "error"))),
                )
                return self._send_json({"result": result, "state": self.application.state()})
            if parsed.path == "/api/simulation/tick":
                if not self.application.simulation_mode:
                    raise ValueError("Fast-forward is only available in simulation")
                query = parse_qs(parsed.query)
                if "steps" in query:
                    steps = int(query["steps"][0])
                else:
                    payload = self._read_json()
                    seconds = float(payload.get("seconds", 60))
                    rate = float(payload.get("rate", 1))
                    return self._send_json(self.application.advance_simulation(seconds, rate))
                return self._send_json(self.application.tick(steps, force=True))
            if parsed.path == "/api/layouts" or parsed.path.startswith("/api/layouts/"):
                payload = self._read_json()
                path_layout_id = parsed.path.removeprefix("/api/layouts/").strip() if parsed.path != "/api/layouts" else ""
                layout_id = path_layout_id or str(payload.get("layout_id", self.application.layout_id))
                record = self.application.save_layout(layout_id, name=payload.get("name"))
                return self._send_json(record, HTTPStatus.CREATED)
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _send_scan_file(self, generated_name: str) -> None:
        with self.application._lock:
            path = self.application._scan_store.resolve(generated_name)
            image_url = f"/api/scans/files/{generated_name}"
            if path is None or not any(scan.get("image") == image_url for scan in self.application.scans):
                return self._send_json({"error": "scan file not found"}, HTTPStatus.NOT_FOUND)
            body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, requested_path: str) -> None:
        requested_path = unquote(requested_path)
        if requested_path.startswith("/scans/"):
            asset_root = self.application._scan_store.directory
            relative = requested_path.removeprefix("/scans/")
        else:
            asset_root = FRONTEND_DIR
            relative = requested_path.removeprefix("/") or "index.html"
        candidate = (asset_root / relative).resolve()
        if asset_root not in candidate.parents and candidate != asset_root:
            return self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
        if not candidate.is_file():
            return self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str = "127.0.0.1", port: int = 8080, application: ControllerApplication | None = None) -> ThreadingHTTPServer:
    app = application or ControllerApplication.sample(database_path="data/controller.sqlite3")

    class BoundHandler(ControllerHandler):
        pass

    BoundHandler.application = app

    class ControllerHTTPServer(ThreadingHTTPServer):
        def server_close(self) -> None:
            app.stop_motion_clock()
            app.stop_background_refresh()
            super().server_close()
            if application is None:
                app.close()

    server = ControllerHTTPServer((host, port), BoundHandler)
    app.start_background_refresh()
    app.start_motion_clock()
    return server


def startup_z21_endpoint(settings: dict[str, Any], environment: dict[str, str] | None = None) -> tuple[str | None, int]:
    """Only explicit process configuration can select physical operation."""

    environment = os.environ if environment is None else environment
    track_system = environment.get("H0_TRACK_SYSTEM", "simulation").strip().lower()
    if track_system not in {"simulation", "z21"}:
        raise ValueError("H0_TRACK_SYSTEM must be simulation or z21")
    host = environment.get("H0_Z21_HOST") or (settings["z21_host"] if track_system == "z21" else None)
    port = int(environment.get("H0_Z21_PORT") or settings["z21_port"])
    if host:
        validated = validate_settings({"z21_host": host, "z21_port": port}, settings)
        return validated["z21_host"], validated["z21_port"]
    return None, port


def startup_z21_transport(
    settings: dict[str, Any],
    environment: dict[str, str] | None = None,
    *,
    wlan_route_api: WindowsRouteAPI | None = None,
    platform_name: str | None = None,
) -> tuple[str | None, int, str, dict[str, Any]]:
    """Resolve the selected transport and preflight WLAN before Z21 creation."""

    validated = validate_settings(settings)
    host, port = startup_z21_endpoint(validated, environment)
    if host is None:
        return None, port, "simulation", {
            "profile": "simulation",
            "state": "inactive",
            "ready": True,
            "host": None,
            "detail": "Simulation does not open a physical network transport.",
        }
    if validated["z21_wlan_enabled"]:
        status = preflight_z21_wlan(host, route_api=wlan_route_api, platform_name=platform_name)
        return host, port, "wlan", status
    return host, port, "lan", {
        "profile": "lan",
        "state": "not_required",
        "ready": True,
        "host": host,
        "detail": "Wired LAN profile selected; WLAN route preflight is not required.",
    }


def run(host: str = "127.0.0.1", port: int = 8080) -> None:
    database_path = os.environ.get("H0_CONTROLLER_DB", "data/controller.sqlite3")
    repository = SQLiteSettingsRepository(database_path)
    try:
        z21_host, z21_port, transport_profile, transport_status = startup_z21_transport(repository.load())
    finally:
        repository.close()
    feedback_map: dict[tuple[int, int], str] = {}
    for token in os.environ.get("H0_Z21_FEEDBACK_MAP", "").split(","):
        if not token.strip() or "=" not in token:
            continue
        sensor, block_id = (part.strip() for part in token.split("=", 1))
        try:
            module, input_number = (int(part) for part in sensor.split(":", 1))
        except ValueError:
            continue
        feedback_map[(module, input_number)] = block_id
    app = ControllerApplication.sample(
        database_path=database_path,
        z21_host=z21_host,
        z21_port=z21_port,
        z21_transport_profile=transport_profile,
        z21_transport_status=transport_status,
        feedback_map=feedback_map,
    )
    server = make_server(host, port, app)
    mode = f"Z21 {transport_profile.upper()} mode via {z21_host}:{z21_port}" if z21_host else "simulation mode"
    print(f"H0 Z21 controller running at http://{host}:{port} ({mode})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
