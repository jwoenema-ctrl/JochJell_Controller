"""Small dependency-free HTTP API for the local H0 controller dashboard.

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
from backend.infrastructure.train_database import DecoderFunctionMapping, MaintenanceRecord, RollingStockRecord, TrainModel
from backend.infrastructure.settings import SQLiteSettingsRepository, validate_settings
from backend.infrastructure.scan_store import MAX_UPLOAD_BODY_BYTES, ScanStore
from backend.runtime import ControllerRuntime
from backend.services.dispatcher import ControlMode
from backend.services.scheduler import ScheduleStop as RuntimeScheduleStop


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
    database_path: str = ":memory:"
    layout_id: str = "default"
    layout_name: str = "Sample H0 layout"
    z21_host: str | None = None
    z21_port: int = 21105
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
        self._sync_runtime_from_ui()
        self._domain_event_subscription = self.runtime.events.subscribe(Event, self._record_domain_event)
        self._last_train_blocks = {str(train.get("id")): str(train.get("block_id", "")) for train in self.trains}
        if self.database_path != ":memory:" and self.runtime.layout_repository.load(self.layout_id) is not None:
            self.load_layout(self.layout_id)

    @classmethod
    def sample(
        cls,
        *,
        database_path: str = ":memory:",
        z21_host: str | None = None,
        z21_port: int = 21105,
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
            database_path=database_path,
            z21_host=z21_host,
            z21_port=z21_port,
            feedback_map=dict(feedback_map or {}),
        )

    def close(self) -> None:
        """Close the composed runtime and its persistence connections."""

        self.stop_background_refresh()
        subscription = getattr(self, "_domain_event_subscription", None)
        if subscription is not None:
            subscription.close()
            self._domain_event_subscription = None
        if self.runtime is not None:
            self.runtime.close()
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
            restart_required = bool(self.z21_host and (self.z21_host != next_host or self.z21_port != next_port))
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
                    "z21_environment_override": bool(os.environ.get("H0_Z21_HOST") or os.environ.get("H0_Z21_PORT")),
                    "restart_required": restart_required,
                    "hardware_activation_required": not bool(self.z21_host),
                    "connection_message": "Saved for the next explicit physical startup; simulation stays active." if not self.z21_host else "Restart physical control to apply the saved endpoint." if restart_required else "Physical endpoint is active. Environment overrides take precedence when set.",
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
            edges=self._topology_edges(),
            stations=self.stations,
            signals=self.signals,
            waypoints=self.waypoints,
            turntables=self.turntables,
            platforms=self.platforms,
            scans=self.scans,
            revision=self.runtime.layout.snapshot().version if self.runtime is not None else 0,
        )

    def _sync_runtime_from_ui(self) -> None:
        """Keep the typed runtime aligned with the current display fixture."""

        if self.runtime is None:
            return
        snapshot = self._domain_snapshot()
        self.runtime.layout.replace(snapshot)
        graph = self.runtime.layout.graph()
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
            if self.z21_host and train.get("address") in (None, ""):
                # A catalogue record may be known before a decoder address is
                # assigned. Keep it in the database/UI, but never register an
                # unaddressed model with the physical command station.
                if train_id in self.runtime.dispatcher.trains:
                    if hasattr(self.runtime.track, "remove_train"):
                        self.runtime.track.remove_train(train_id)
                    self.runtime.dispatcher.unregister_train(train_id)
                continue
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
            desired_route = tuple(str(item).upper() for item in train.get("route", ()) if str(item)) or tuple(self.runtime.route_updater.desired_routes.get(train_id, ()))
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
            self.runtime.dispatcher.set_mode(train_id, mode)
            if self.z21_host:
                # A physical layout is observed/commanded only after the user
                # sends an explicit UI command; startup should not move trains.
                continue
            if mode is ControlMode.STOPPED:
                continue
            normalized = max(0.0, min(1.0, float(train.get("speed", 0)) / max(1.0, float(train.get("maxSpeed", 140)))))
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
            self.runtime.scheduler.start(tick=current_tick)

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
            }
        if train_id is not None:
            record = self.runtime.train_database.get(self._canonical_train_id(str(train_id)))
            return serialize(record) if record is not None else None
        return [serialize(record) for record in records]

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
                "length": (model.length_mm / 1000) if model.length_mm is not None else row.get("length", ""),
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
                train["speed"] = round(float(motion.target_speed) * float(train.get("maxSpeed", 140)))
                if previous_blocks.get(train_id) is None:
                    current_blocks[train_id] = str(motion.block_id)
        self._last_train_blocks = current_blocks

    def _snapshot(self) -> dict[str, Any]:
        connection = self.runtime.connection.status if self.runtime is not None else None
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

    def _ui_snapshot(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "simulation_mode": snapshot["simulation_mode"],
            "mode": "simulation" if self.simulation_mode else "manual",
            "connection": {
                "connected": snapshot["connected"],
                "simulated": snapshot["simulation_mode"],
                "mode": snapshot["connection"]["mode"],
                "endpoint": snapshot["connection"]["endpoint"],
                "label": "Simulation fallback" if snapshot["simulation_mode"] else "Z21 controller online",
                "detail": "Local sample state" if snapshot["simulation_mode"] else "Z21 LAN adapter",
            },
            "simulation": {
                "running": self.simulation_running,
                "rate": 1,
                "clock": f"{(self.tick_count * 60 // 3600) % 24:02d}:{(self.tick_count * 60 // 60) % 60:02d}:{(self.tick_count * 60) % 60:02d}",
                "date": "Simulation",
            },
            "tick": snapshot["tick"],
            "track_power": snapshot["track_power"],
            "feedback": snapshot["feedback"],
            "layout": {
                "name": self.layout_name,
                "blocks": self._ui_blocks(),
                "edges": self._ui_edges(),
                "turnouts": self._ui_turnouts(),
                "stations": list(self.stations),
                "signals": list(self.signals),
                "waypoints": list(self.waypoints),
                "turntables": list(self.turntables),
                "platforms": list(self.platforms) or [
                    {"id": "p1", "name": "Central station", "blockIds": ["b01", "b02"]},
                    {"id": "p2", "name": "East platform", "blockIds": ["b03"]},
                    {"id": "p3", "name": "Yard", "blockIds": ["b04"]},
                ],
            },
            "trains": self._ui_trains(),
            "trainDatabase": self.train_database(),
            "schedules": list(self.schedules),
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
            occupants = [train["id"] for train in self.trains if train.get("block_id") == block_id]
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
        return [{"from": left, "to": right, "status": "free"} for left, right in sorted(links)]

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
        return [{"from": left, "to": right, "status": "free"} for left, right in sorted(links)]

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

    def _ui_trains(self) -> list[dict[str, Any]]:
        result = []
        for train in self.trains:
            ui_id = self._ui_train_id(train["id"])
            raw_length = train.get("length_mm")
            if raw_length in (None, ""):
                raw_length = 0
            try:
                display_length = round(float(raw_length) / 1000, 2)
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
                "position": train.get("block_id", "—"),
                "route": train.get("route", []),
                "destination_block_id": train.get("destination_block_id"),
                "origin": train.get("origin", "Layout"),
                "destination": train.get("destination", "Layout"),
                "direction": "Forward" if train.get("direction") == "forward" else "Reverse",
                "decoder": f"Z21-{train.get('address', '')}",
                "manufacturer": train.get("manufacturer", ""),
                "model_number": train.get("model_number", train.get("model", "")),
                "era": train.get("era", ""),
                "mass_g": train.get("mass_g"),
                "decoder_protocol": train.get("decoder_protocol", "DCC"),
                "length": display_length,
                "maxSpeed": max_speed,
                "consist": train.get("consist", []),
            })
        return result

    def tick(self, steps: int = 1) -> dict[str, Any]:
        with self._lock:
            safe_steps = max(1, min(int(steps), 100))
            if not self.simulation_running:
                self.events.append({"type": "simulation_tick_skipped", "reason": "simulation paused"})
                return self._ui_snapshot()
            if self.runtime is not None:
                self.runtime.tick(safe_steps)
                schedule_events = self.runtime.scheduler.advance(safe_steps) if self.runtime.scheduler.running else ()
                for schedule_event in schedule_events:
                    state = "Arrived" if schedule_event.kind.value == "arrival" else "Departed"
                    schedule_id = str(schedule_event.stop.stop_id).split("#", 1)[0]
                    row = next((item for item in self.schedules if item.get("id") == schedule_id), None)
                    if row is not None:
                        row["state"] = state
                    self._publish_domain_event(
                        ScheduleStateChanged(
                            schedule_id=schedule_id,
                            status=ScheduleStatus.COMPLETED if state == "Arrived" else ScheduleStatus.ACTIVE,
                        )
                    )
                    self.events.append({"type": f"schedule_{schedule_event.kind.value}", "schedule_id": schedule_id, "stop_id": schedule_event.stop.stop_id, "train_id": schedule_event.stop.train_id, "tick": schedule_event.tick})
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
        self.scans = projected.get("scans", self.scans)
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
                turnouts=self.turnouts,
                trains=self.trains,
                schedules=self.schedules,
                edges=self._topology_edges(),
                stations=collections.get("stations", self.stations),
                signals=collections.get("signals", self.signals),
                waypoints=collections.get("waypoints", self.waypoints),
                turntables=collections.get("turntables", self.turntables),
                platforms=collections.get("platforms", self.platforms),
                scans=self.scans,
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
        if len(parts) != 2 or parts[0] not in {"add", "update", "remove", "delete"} or parts[1] not in {"station", "signal", "waypoint", "turntable", "platform"}:
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

    def command(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            kind = str(payload.get("type", "")).lower()
            if kind in {"speed", "set_speed", "drive"}:
                train_id = self._canonical_train_id(str(payload.get("train_id", "")))
                train = next((item for item in self.trains if item["id"] == train_id), None)
                if train is None:
                    raise ValueError(f"Unknown train: {train_id}")
                requested_speed = payload.get("speed", payload.get("speed_kmh", 0))
                train["speed"] = max(0, min(140, int(requested_speed)))
                if "direction" in payload:
                    train["direction"] = str(payload["direction"])
                if self.runtime is not None:
                    normalized = train["speed"] / max(1.0, float(train.get("maxSpeed", 140)))
                    control = self.runtime.dispatcher.register_train(train_id)
                    if control.mode is ControlMode.AUTOMATIC:
                        result = self.runtime.dispatcher.automatic_speed(train_id, normalized)
                    else:
                        result = self.runtime.dispatcher.manual_speed(train_id, normalized)
                    if hasattr(result, "accepted") and not result.accepted:
                        raise ValueError(result.detail or "train speed command rejected")
                self._publish_domain_event(
                    TrainSpeedChanged(
                        train_id=train_id,
                        speed_kmh=float(train["speed"]),
                        mode=TrainMode.AUTOMATIC if str(train.get("mode", "manual")).lower() == "automatic" else TrainMode.MANUAL,
                    )
                )
                self.events.append({"type": "train_command", "train_id": train_id, "speed": train["speed"]})
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
                self._sync_train_database()
            elif kind == "add_train":
                train = dict(payload.get("train", {}))
                train_id = str(train.get("id", "")).strip()
                if not train_id or any(item.get("id") == train_id for item in self.trains):
                    raise ValueError("train ID is required and must be unique")
                train.setdefault("name", "New service")
                train.setdefault("address", None)
                train.setdefault("mode", "manual")
                train.setdefault("speed", 0)
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
                train["consist"] = list(payload.get("consist", []))
                self._sync_train_database()
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
                block_id = str(block.get("id", "")).strip()
                if not block_id or any(item.get("id") == block_id for item in self.blocks):
                    raise ValueError("block ID is required and must be unique")
                block["id"] = block_id
                block.setdefault("name", block_id)
                block.setdefault("x", 62)
                block.setdefault("y", 224)
                block.setdefault("status", "free")
                self.blocks.append(block)
                self._sync_runtime_from_ui()
                self.events.append({"type": "block_added", "block_id": block_id})
            elif kind == "update_block":
                block_id = str(payload.get("block_id", payload.get("id", ""))).strip().upper()
                block = next((item for item in self.blocks if str(item.get("id", "")).upper() == block_id), None)
                if block is None:
                    raise ValueError(f"Unknown block: {block_id}")
                updates = dict(payload.get("block", {}))
                if "name" in updates:
                    block["name"] = str(updates["name"]).strip() or block_id
                if "length_mm" in updates:
                    block["length_mm"] = max(0, float(updates["length_mm"]))
                if "station" in updates:
                    block["station"] = str(updates["station"]).strip()
                self._sync_runtime_from_ui()
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
            elif kind == "add_schedule":
                schedule = dict(payload.get("schedule", {}))
                schedule_id = str(schedule.get("id", "")).strip()
                if not schedule_id or any(item.get("id") == schedule_id for item in self.schedules):
                    raise ValueError("schedule ID is required and must be unique")
                schedule.setdefault("time", "11:15")
                schedule.setdefault("service", "New service")
                schedule.setdefault("number", "NEW")
                schedule.setdefault("state", "Draft")
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
                schedule.update(dict(payload.get("schedule", {})))
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
                current_tick = self.runtime.scheduler.current_tick
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
                schedule_events = self.runtime.scheduler.simulate(until_tick) if self.runtime is not None else ()
                for schedule_event in schedule_events:
                    state = "Arrived" if schedule_event.kind.value == "arrival" else "Departed"
                    schedule_id = str(schedule_event.stop.stop_id).split("#", 1)[0]
                    row = next((item for item in self.schedules if item.get("id") == schedule_id), None)
                    if row is not None:
                        row["state"] = state
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
                    train["speed"] = 0
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
                            train["speed"] = 0
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
            if self.application.runtime is not None:
                connection = self.application.runtime.connection.check()
                if self.application.z21_host and not connection.status.connected:
                    # A dashboard health check is also a safety boundary.  If
                    # the command station disappears while the runtime is
                    # paused, stop application targets immediately instead of
                    # waiting for the next dispatch tick.
                    self.application.runtime.dispatcher.emergency_stop()
                    self.application.track_power = False
                    for train in self.application.trains:
                        train["mode"] = ControlMode.STOPPED.value
                        train["speed"] = 0
                    self.application._sync_ui_from_runtime()
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
                query = parse_qs(parsed.query)
                if "steps" in query:
                    steps = int(query["steps"][0])
                else:
                    payload = self._read_json()
                    seconds = float(payload.get("seconds", 60))
                    rate = float(payload.get("rate", 1))
                    steps = max(1, math.ceil((seconds / 60) * rate))
                return self._send_json(self.application.tick(steps))
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
            asset_root = SCAN_DIR
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
            app.stop_background_refresh()
            super().server_close()
            if application is None:
                app.close()

    server = ControllerHTTPServer((host, port), BoundHandler)
    app.start_background_refresh()
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


def run(host: str = "127.0.0.1", port: int = 8080) -> None:
    database_path = os.environ.get("H0_CONTROLLER_DB", "data/controller.sqlite3")
    repository = SQLiteSettingsRepository(database_path)
    try:
        z21_host, z21_port = startup_z21_endpoint(repository.load())
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
    app = ControllerApplication.sample(database_path=database_path, z21_host=z21_host, z21_port=z21_port, feedback_map=feedback_map)
    server = make_server(host, port, app)
    mode = f"Z21 LAN mode via {z21_host}:{z21_port}" if z21_host else "simulation mode"
    print(f"H0 Z21 controller running at http://{host}:{port} ({mode})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
