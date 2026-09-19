"""Geometry helpers for the coordinate-aware 2D track pinboard."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping


@dataclass(frozen=True)
class TrackCoordinate:
    """A point projected onto one connected track segment."""

    x: float
    y: float
    from_node: str
    to_node: str
    distance_to_track: float
    progress: float


def block_center(block: Mapping[str, object]) -> tuple[float, float]:
    return (
        float(block.get("x", 0) or 0) + float(block.get("width", 126) or 126) / 2,
        float(block.get("y", 0) or 0) + float(block.get("height", 56) or 56) / 2,
    )


def _control_points(edge: Mapping[str, object]) -> tuple[tuple[float, float], ...]:
    """Read optional waypoint/control points carried by an edge."""

    raw = edge.get("control_points", edge.get("controlPoints", ()))
    if not isinstance(raw, (list, tuple)):
        return ()
    points: list[tuple[float, float]] = []
    for value in raw:
        if not isinstance(value, Mapping):
            continue
        try:
            x, y = float(value.get("x")), float(value.get("y"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            points.append((x, y))
    return tuple(points)


def _project_polyline(points: tuple[tuple[float, float], ...], x: float, y: float) -> tuple[float, float, float, float] | None:
    """Return projected x/y and normalized progress along a polyline."""

    if len(points) < 2:
        return None
    lengths = [math.hypot(points[index + 1][0] - points[index][0], points[index + 1][1] - points[index][1]) for index in range(len(points) - 1)]
    total = sum(lengths)
    if total <= 0:
        return None
    best: tuple[float, float, float, float] | None = None
    travelled = 0.0
    for index, length in enumerate(lengths):
        if length <= 0:
            continue
        ax, ay = points[index]
        bx, by = points[index + 1]
        dx, dy = bx - ax, by - ay
        local = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (length * length)))
        px, py = ax + dx * local, ay + dy * local
        distance = math.hypot(x - px, y - py)
        progress = (travelled + length * local) / total
        if best is None or distance < best[0]:
            best = (distance, px, py, progress)
        travelled += length
    if best is None:
        return None
    distance, px, py, progress = best
    return px, py, progress, distance


def nearest_track_coordinate(
    blocks: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
    x: float,
    y: float,
    *,
    tolerance: float = 32.0,
) -> TrackCoordinate | None:
    """Return the nearest point on the configured graph, if within tolerance."""

    if not math.isfinite(float(x)) or not math.isfinite(float(y)):
        raise ValueError("track coordinate must be finite")
    by_id = {str(block.get("id", "")).strip().upper(): block for block in blocks if str(block.get("id", "")).strip()}
    best: TrackCoordinate | None = None
    for edge in edges:
        left = str(edge.get("from", "")).strip().upper()
        right = str(edge.get("to", "")).strip().upper()
        if left not in by_id or right not in by_id or left == right:
            continue
        points = (block_center(by_id[left]), *_control_points(edge), block_center(by_id[right]))
        projected = _project_polyline(points, float(x), float(y))
        if projected is None:
            continue
        px, py, progress, distance = projected
        candidate = TrackCoordinate(px, py, left, right, distance, progress)
        if best is None or candidate.distance_to_track < best.distance_to_track:
            best = candidate
    return best if best is not None and best.distance_to_track <= tolerance else None
