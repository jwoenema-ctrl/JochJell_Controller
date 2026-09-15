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
        ax, ay = block_center(by_id[left])
        bx, by = block_center(by_id[right])
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        progress = max(0.0, min(1.0, ((float(x) - ax) * dx + (float(y) - ay) * dy) / length_squared)) if length_squared else 0.0
        px, py = ax + dx * progress, ay + dy * progress
        distance = math.hypot(float(x) - px, float(y) - py)
        candidate = TrackCoordinate(px, py, left, right, distance, progress)
        if best is None or candidate.distance_to_track < best.distance_to_track:
            best = candidate
    return best if best is not None and best.distance_to_track <= tolerance else None
