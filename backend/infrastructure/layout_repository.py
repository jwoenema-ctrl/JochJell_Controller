"""SQLite persistence for immutable core layout snapshots."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, TypeVar

from backend.core.models import (
    Block,
    BlockState,
    ConnectionSpeedLimit,
    LayoutSnapshot,
    Platform,
    PhotoScan,
    Point,
    RouteDefinition,
    Schedule,
    ScheduleStatus,
    ScheduleStop,
    Signal,
    SignalAspect,
    Station,
    Train,
    TrainMode,
    TrainModelInfo,
    TrainStatus,
    Turnout,
    TurnoutPosition,
    Turntable,
    Waypoint,
)


@dataclass(frozen=True)
class LayoutRecord:
    """Metadata returned when listing saved layouts."""

    layout_id: str
    name: str
    revision: int
    updated_at: str


_T = TypeVar("_T")


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def snapshot_to_dict(snapshot: LayoutSnapshot) -> dict[str, Any]:
    """Convert a domain snapshot to a JSON-compatible dictionary."""

    if not isinstance(snapshot, LayoutSnapshot):
        raise TypeError("snapshot must be a LayoutSnapshot")
    return _json_value(snapshot)


def _tuple(value: Any) -> tuple[Any, ...]:
    return tuple(value or ())


def _point(value: Any) -> Point | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("point must be an object")
    return Point(float(value["x"]), float(value["y"]))


def _build_entity(entity_type: type[_T], value: Any) -> _T:
    if not isinstance(value, Mapping):
        raise ValueError(f"{entity_type.__name__} must be an object")
    data = dict(value)
    if entity_type is Block:
        data["state"] = BlockState(data.get("state", BlockState.FREE.value))
        for key in ("neighbor_ids", "waypoint_ids", "platform_ids"):
            data[key] = _tuple(data.get(key))
        data["position"] = _point(data.get("position"))
    elif entity_type is Turnout:
        data["position"] = TurnoutPosition(data.get("position", TurnoutPosition.UNKNOWN.value))
    elif entity_type is Station:
        for key in ("block_ids", "platform_ids", "waypoint_ids"):
            data[key] = _tuple(data.get(key))
    elif entity_type is Signal:
        data["aspect"] = SignalAspect(data.get("aspect", SignalAspect.RED.value))
    elif entity_type is Waypoint:
        data["connected_node_ids"] = _tuple(data.get("connected_node_ids"))
        data["position"] = _point(data.get("position"))
    elif entity_type is Turntable:
        data["connected_block_ids"] = _tuple(data.get("connected_block_ids"))
        data["position"] = _point(data.get("position"))
    elif entity_type is PhotoScan:
        data["anchor"] = _point(data.get("anchor"))
    elif entity_type is Train:
        data["model"] = _build_entity(TrainModelInfo, data.get("model", {}))
        data["mode"] = TrainMode(data.get("mode", TrainMode.MANUAL.value))
        data["status"] = TrainStatus(data.get("status", TrainStatus.STOPPED.value))
        data["consist_ids"] = _tuple(data.get("consist_ids"))
    elif entity_type is Schedule:
        data["stops"] = tuple(_build_entity(ScheduleStop, item) for item in data.get("stops", ()))
        data["status"] = ScheduleStatus(data.get("status", ScheduleStatus.PLANNED.value))
    elif entity_type is RouteDefinition:
        data["node_ids"] = _tuple(data.get("node_ids", data.get("blocks", data.get("path", ()))))
    return entity_type(**data)


def snapshot_from_dict(value: Mapping[str, Any]) -> LayoutSnapshot:
    """Reconstruct and validate a :class:`LayoutSnapshot` from JSON data."""

    if not isinstance(value, Mapping):
        raise ValueError("layout data must be an object")
    return LayoutSnapshot(
        revision=int(value.get("revision", 0)),
        blocks=tuple(_build_entity(Block, item) for item in value.get("blocks", ())),
        turnouts=tuple(_build_entity(Turnout, item) for item in value.get("turnouts", ())),
        stations=tuple(_build_entity(Station, item) for item in value.get("stations", ())),
        signals=tuple(_build_entity(Signal, item) for item in value.get("signals", ())),
        waypoints=tuple(_build_entity(Waypoint, item) for item in value.get("waypoints", ())),
        turntables=tuple(_build_entity(Turntable, item) for item in value.get("turntables", ())),
        platforms=tuple(_build_entity(Platform, item) for item in value.get("platforms", ())),
        trains=tuple(_build_entity(Train, item) for item in value.get("trains", ())),
        schedules=tuple(_build_entity(Schedule, item) for item in value.get("schedules", ())),
        routes=tuple(_build_entity(RouteDefinition, item) for item in value.get("routes", ())),
        scans=tuple(_build_entity(PhotoScan, item) for item in value.get("scans", ())),
        connection_limits=tuple(_build_entity(ConnectionSpeedLimit, item) for item in value.get("connection_limits", ())),
    )


class SQLiteLayoutRepository:
    """Thread-safe SQLite repository for versioned layout snapshots."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._initialise()

    def _initialise(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS layouts (
                    layout_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, layout_id: str, snapshot: LayoutSnapshot, *, name: str | None = None) -> LayoutRecord:
        """Insert or replace a layout snapshot and return its metadata."""

        if not layout_id or not layout_id.strip():
            raise ValueError("layout_id is required")
        if not isinstance(snapshot, LayoutSnapshot):
            raise TypeError("snapshot must be a LayoutSnapshot")
        layout_name = (name or layout_id).strip()
        if not layout_name:
            raise ValueError("name is required")
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(snapshot_to_dict(snapshot), sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO layouts (layout_id, name, revision, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(layout_id) DO UPDATE SET
                    name = excluded.name,
                    revision = excluded.revision,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (layout_id, layout_name, snapshot.revision, payload, updated_at),
            )
        return LayoutRecord(layout_id, layout_name, snapshot.revision, updated_at)

    def load(self, layout_id: str) -> LayoutSnapshot | None:
        """Load a layout by ID, validating its complete domain shape."""

        with self._lock:
            row = self._connection.execute("SELECT data_json FROM layouts WHERE layout_id = ?", (layout_id,)).fetchone()
        if row is None:
            return None
        return snapshot_from_dict(json.loads(row["data_json"]))

    def list(self) -> tuple[LayoutRecord, ...]:
        """List saved layouts in stable name/ID order."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT layout_id, name, revision, updated_at FROM layouts ORDER BY name COLLATE NOCASE, layout_id"
            ).fetchall()
        return tuple(LayoutRecord(row["layout_id"], row["name"], row["revision"], row["updated_at"]) for row in rows)

    def delete(self, layout_id: str) -> bool:
        """Delete one saved layout."""

        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM layouts WHERE layout_id = ?", (layout_id,))
        return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteLayoutRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
