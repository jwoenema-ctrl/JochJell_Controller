"""Plan safe movement from a pinboard coordinate to a neighbouring block.

This module is intentionally independent from the controller runtime.  Callers
inject the layout topology and calibration records, then decide whether and
when to execute the returned plan.  That keeps coordinate interpretation and
duration estimation testable without a live Z21 connection.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


class MovementPlanValidationError(ValueError):
    """A coordinate movement request cannot be made safe from its inputs."""

    def __init__(self, message: str, *, field: str = "movement") -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class CoordinateMovementPlan:
    """A bounded movement from a point on one segment to its destination block."""

    train_id: str
    x: float
    y: float
    source_block_id: str
    target_block_id: str
    progress: float
    distance_mm: float
    speed_kmh: float
    estimated_duration_ms: int
    segment_length_mm: float
    calibration_speed_kmh: float
    calibration_duration_ms: int

    @property
    def source_block(self) -> str:
        """Alias useful to integrations that use the shorter field name."""

        return self.source_block_id

    @property
    def target_block(self) -> str:
        """Alias useful to integrations that use the shorter field name."""

        return self.target_block_id


class CoordinateMovementPlanner:
    """Convert pinboard coordinates into conservative, finite movement plans.

    ``blocks`` and ``edges`` are injected iterables.  A block needs an ``id``
    and either ``x``/``y`` (optionally ``width``/``height``) or a ``position``
    containing ``x``/``y``.  An edge needs ``from`` and ``to``.  Segment length
    is read from an edge's ``length_mm`` first, then from a block's
    ``length_mm``, and finally derived from layout units multiplied by
    ``layout_scale_mm``.

    Calibration may be one record or an iterable of records.  Each record
    needs speed, duration, and measured distance fields.  The nearest measured
    speed is selected; a caller can cap the accepted difference with
    ``max_speed_delta_kmh``.
    """

    def __init__(
        self,
        blocks: Iterable[Mapping[str, Any] | object],
        edges: Iterable[Mapping[str, Any] | object],
        calibrations: Iterable[Mapping[str, Any] | object] | Mapping[str, Any] | object,
        *,
        layout_scale_mm: float = 1.0,
        coordinate_tolerance: float = 32.0,
        max_speed_delta_kmh: float | None = None,
    ) -> None:
        self._blocks = tuple(blocks)
        self._edges = tuple(edges)
        self._calibrations = _records(calibrations)
        self._layout_scale_mm = _positive_finite(layout_scale_mm, "layout_scale_mm")
        self._coordinate_tolerance = _non_negative_finite(coordinate_tolerance, "coordinate_tolerance")
        if max_speed_delta_kmh is not None:
            self._max_speed_delta_kmh = _non_negative_finite(max_speed_delta_kmh, "max_speed_delta_kmh")
        else:
            self._max_speed_delta_kmh = None
        self._block_by_id: dict[str, object] = {}
        for block in self._blocks:
            block_id = _id(block, "block")
            if block_id in self._block_by_id:
                raise MovementPlanValidationError(f"duplicate block ID: {block_id}", field="blocks")
            self._block_by_id[block_id] = block

    def plan(
        self,
        train_id: str,
        x: float,
        y: float,
        *,
        speed_kmh: float | None = None,
        direction: str = "forward",
        occupied_blocks: Mapping[str, Any] | Iterable[str] | None = None,
    ) -> CoordinateMovementPlan:
        """Build a plan to the end block of the segment under ``direction``.

        ``forward`` follows each edge's ``from`` → ``to`` orientation.  The
        reverse direction swaps source/target and the remaining distance.  An
        occupied target is rejected when its occupant is another train.
        """

        train_id = _required_text(train_id, "train_id")
        x = _finite(x, "x")
        y = _finite(y, "y")
        direction = _required_text(direction, "direction").lower()
        if direction not in {"forward", "reverse"}:
            raise MovementPlanValidationError("direction must be 'forward' or 'reverse'", field="direction")

        requested_speed = self._select_speed(speed_kmh)
        calibration = self._select_calibration(requested_speed)
        edge, progress, segment_length_mm = self._locate_segment(x, y)
        left, right = _required_text(_value(edge, "from", "from_block_id"), "edge.from"), _required_text(
            _value(edge, "to", "to_block_id"), "edge.to"
        )
        if direction == "forward":
            source, target = left, right
            remaining_progress = 1.0 - progress
        else:
            source, target = right, left
            remaining_progress = progress
        if source not in self._block_by_id or target not in self._block_by_id:
            raise MovementPlanValidationError("track segment references an unknown block", field="topology")
        self._validate_occupancy(target, train_id, occupied_blocks)

        distance_mm = segment_length_mm * remaining_progress
        speed_per_ms = float(_value(calibration, "measured_distance_mm", "distance_mm")) / float(
            _value(calibration, "duration_ms", "duration")
        )
        estimated_duration_ms = max(0, math.ceil(distance_mm / speed_per_ms)) if distance_mm else 0
        return CoordinateMovementPlan(
            train_id=train_id,
            x=x,
            y=y,
            source_block_id=source,
            target_block_id=target,
            progress=progress,
            distance_mm=distance_mm,
            speed_kmh=requested_speed,
            estimated_duration_ms=estimated_duration_ms,
            segment_length_mm=segment_length_mm,
            calibration_speed_kmh=float(_value(calibration, "speed_kmh", "speed")),
            calibration_duration_ms=int(_value(calibration, "duration_ms", "duration")),
        )

    def _locate_segment(self, x: float, y: float) -> tuple[object, float, float]:
        best: tuple[float, object, float, float] | None = None
        for edge in self._edges:
            left = _required_text(_value(edge, "from", "from_block_id"), "edge.from")
            right = _required_text(_value(edge, "to", "to_block_id"), "edge.to")
            if left not in self._block_by_id or right not in self._block_by_id or left == right:
                continue
            ax, ay = _center(self._block_by_id[left])
            bx, by = _center(self._block_by_id[right])
            dx, dy = bx - ax, by - ay
            length_squared = dx * dx + dy * dy
            if length_squared <= 0:
                continue
            progress = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_squared))
            px, py = ax + dx * progress, ay + dy * progress
            distance = math.hypot(x - px, y - py)
            length_mm = _segment_length(edge, self._block_by_id[left], self._block_by_id[right], math.sqrt(length_squared), self._layout_scale_mm)
            candidate = (distance, edge, progress, length_mm)
            if best is None or distance < best[0]:
                best = candidate
        if best is None or best[0] > self._coordinate_tolerance:
            raise MovementPlanValidationError("coordinate is not on a configured track segment", field="coordinate")
        return best[1], best[2], best[3]

    def _select_speed(self, speed_kmh: float | None) -> float:
        if speed_kmh is not None:
            return _positive_finite(speed_kmh, "speed_kmh")
        if not self._calibrations:
            raise MovementPlanValidationError("a calibration record is required", field="calibration")
        return _positive_finite(_value(self._calibrations[0], "speed_kmh", "speed"), "calibration.speed_kmh")

    def _select_calibration(self, speed_kmh: float) -> object:
        if not self._calibrations:
            raise MovementPlanValidationError("a calibration record is required", field="calibration")
        candidates: list[tuple[float, object]] = []
        for record in self._calibrations:
            try:
                record_speed = _positive_finite(_value(record, "speed_kmh", "speed"), "calibration.speed_kmh")
                duration = _positive_finite(_value(record, "duration_ms", "duration"), "calibration.duration_ms")
                distance = _positive_finite(_value(record, "measured_distance_mm", "distance_mm"), "calibration.measured_distance_mm")
            except (KeyError, TypeError, ValueError) as exc:
                raise MovementPlanValidationError(f"invalid calibration record: {exc}", field="calibration") from exc
            if duration and distance:
                candidates.append((abs(record_speed - speed_kmh), record))
        if not candidates:
            raise MovementPlanValidationError("calibration must contain positive duration and distance", field="calibration")
        delta, record = min(candidates, key=lambda item: item[0])
        if self._max_speed_delta_kmh is not None and delta > self._max_speed_delta_kmh:
            raise MovementPlanValidationError("no calibration is available near the requested speed", field="calibration")
        return record

    @staticmethod
    def _validate_occupancy(target: str, train_id: str, occupied_blocks: Mapping[str, Any] | Iterable[str] | None) -> None:
        if occupied_blocks is None:
            return
        if isinstance(occupied_blocks, Mapping):
            occupant = occupied_blocks.get(target)
            if isinstance(occupant, (list, tuple, set, frozenset)):
                occupied = {str(item) for item in occupant}
            elif occupant is None or occupant is False:
                occupied = set()
            else:
                occupied = {str(occupant)}
        else:
            occupied = {str(item) for item in occupied_blocks}
        if occupied - {train_id}:
            raise MovementPlanValidationError(f"target block {target} is occupied", field="occupancy")


def _records(value: Iterable[Mapping[str, Any] | object] | Mapping[str, Any] | object) -> tuple[object, ...]:
    if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return (value,)


def _value(value: object, *names: str) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    raise KeyError(names[0])


def _id(value: object, kind: str) -> str:
    try:
        return _required_text(_value(value, "id", f"{kind}_id"), f"{kind}.id")
    except KeyError as exc:
        raise MovementPlanValidationError(f"{kind} must have an id", field="topology") from exc


def _center(block: object) -> tuple[float, float]:
    try:
        position = _value(block, "position")
    except KeyError:
        position = None
    if position is not None:
        return _finite(_value(position, "x"), "block.position.x"), _finite(_value(position, "y"), "block.position.y")
    x = _finite(_value(block, "x"), "block.x")
    y = _finite(_value(block, "y"), "block.y")
    width = float(_value(block, "width")) if _has(block, "width") else 0.0
    height = float(_value(block, "height")) if _has(block, "height") else 0.0
    return x + width / 2.0, y + height / 2.0


def _segment_length(edge: object, left: object, right: object, layout_distance: float, scale: float) -> float:
    edge_length = _value_or_none(edge, "length_mm")
    if edge_length is not None:
        return _positive_finite(edge_length, "edge.length_mm")
    for value in (_value_or_none(left, "length_mm"), _value_or_none(right, "length_mm")):
        # Block.length_mm defaults to zero in the domain model when no physical
        # measurement is configured; in that case use the injected layout scale.
        if value is not None and float(value) > 0:
            return _positive_finite(value, "block.length_mm")
    return _positive_finite(layout_distance * scale, "derived segment length")


def _value_or_none(value: object, name: str) -> Any:
    try:
        return _value(value, name)
    except KeyError:
        return None


def _has(value: object, name: str) -> bool:
    return isinstance(value, Mapping) and name in value or hasattr(value, name)


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MovementPlanValidationError(f"{field} must be a non-empty string", field=field)
    return value.strip()


def _finite(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MovementPlanValidationError(f"{field} must be a finite number", field=field) from exc
    if not math.isfinite(result):
        raise MovementPlanValidationError(f"{field} must be a finite number", field=field)
    return result


def _positive_finite(value: Any, field: str) -> float:
    result = _finite(value, field)
    if result <= 0:
        raise MovementPlanValidationError(f"{field} must be positive", field=field)
    return result


def _non_negative_finite(value: Any, field: str) -> float:
    result = _finite(value, field)
    if result < 0:
        raise MovementPlanValidationError(f"{field} must be non-negative", field=field)
    return result


# Short alias makes the result type easy to discover for callers and tests.
MovementPlan = CoordinateMovementPlan


def plan_coordinate_movement(
    train_id: str,
    x: float,
    y: float,
    *,
    blocks: Iterable[Mapping[str, Any] | object],
    edges: Iterable[Mapping[str, Any] | object],
    calibrations: Iterable[Mapping[str, Any] | object] | Mapping[str, Any] | object,
    speed_kmh: float | None = None,
    direction: str = "forward",
    occupied_blocks: Mapping[str, Any] | Iterable[str] | None = None,
    layout_scale_mm: float = 1.0,
    coordinate_tolerance: float = 32.0,
    max_speed_delta_kmh: float | None = None,
) -> CoordinateMovementPlan:
    """Convenience wrapper for one-shot coordinate movement planning."""

    return CoordinateMovementPlanner(
        blocks,
        edges,
        calibrations,
        layout_scale_mm=layout_scale_mm,
        coordinate_tolerance=coordinate_tolerance,
        max_speed_delta_kmh=max_speed_delta_kmh,
    ).plan(
        train_id,
        x,
        y,
        speed_kmh=speed_kmh,
        direction=direction,
        occupied_blocks=occupied_blocks,
    )
