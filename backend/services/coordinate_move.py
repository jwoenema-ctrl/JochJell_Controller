"""Plan safe movement from a pinboard coordinate to a neighbouring block.

This module is intentionally independent from the controller runtime.  Callers
inject the layout topology and calibration records, then decide whether and
when to execute the returned plan.  That keeps coordinate interpretation and
duration estimation testable without a live Z21 connection.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Any, Callable, Iterable, Mapping


class MovementPlanValidationError(ValueError):
    """A coordinate movement request cannot be made safe from its inputs."""

    def __init__(self, message: str, *, field: str = "movement") -> None:
        super().__init__(message)
        self.field = field


class MovementExecutionError(RuntimeError):
    """A timed coordinate movement could not be safely started or stopped."""

    def __init__(self, message: str, *, field: str = "execution") -> None:
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
    direction: str = "forward"

    @property
    def source_block(self) -> str:
        """Alias useful to integrations that use the shorter field name."""

        return self.source_block_id

    @property
    def target_block(self) -> str:
        """Alias useful to integrations that use the shorter field name."""

        return self.target_block_id


@dataclass(frozen=True, slots=True)
class TimedMovementRequest:
    """A validated, hardware-neutral request for one bounded movement."""

    train_id: str
    direction: str
    speed_kmh: float
    duration_ms: int
    stop_after: bool = True

    @property
    def stop_after_ms(self) -> int | None:
        """The timer deadline, when the request has stop-after semantics."""

        return self.duration_ms if self.stop_after else None


@dataclass(frozen=True, slots=True)
class CoordinateMovementExecutionPlan:
    """Validated execution data derived from a coordinate plan and calibration."""

    movement_plan: CoordinateMovementPlan
    calibration_speed_kmh: float
    calibration_duration_ms: int
    measured_distance_mm: float
    request: TimedMovementRequest

    @property
    def train_id(self) -> str:
        return self.request.train_id

    @property
    def direction(self) -> str:
        return self.request.direction

    @property
    def speed_kmh(self) -> float:
        return self.request.speed_kmh

    @property
    def duration_ms(self) -> int:
        return self.request.duration_ms

    @property
    def stop_after(self) -> bool:
        return self.request.stop_after

    @property
    def stop_after_ms(self) -> int | None:
        return self.request.stop_after_ms

    def timed_request(self) -> TimedMovementRequest:
        """Return the data-only request suitable for a runtime adapter."""

        return self.request


@dataclass(frozen=True, slots=True)
class MovementExecutionStatus:
    """Observable state for one runtime-owned timed movement."""

    state: str
    request: TimedMovementRequest | None = None
    error: str = ""

    @property
    def running(self) -> bool:
        return self.state == "running"


class CoordinateMovementExecutor:
    """Execute one confirmed coordinate request with a bounded stop timer.

    Planning never sends commands.  This service is the explicit runtime
    boundary: callers must pass ``confirmed=True`` before it can set direction
    or speed.  The executor owns the timer and sends the stop operation when
    the request expires, including when a caller closes or cancels it.
    """

    DEFAULT_MAX_DURATION_MS = 120_000

    def __init__(
        self,
        dispatcher: Any,
        track: Any,
        *,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
        max_duration_ms: int = DEFAULT_MAX_DURATION_MS,
        max_speed_kmh: float = 140.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(max_duration_ms, bool) or int(max_duration_ms) != max_duration_ms:
            raise MovementExecutionError("max_duration_ms must be a whole number", field="duration_ms")
        if max_duration_ms <= 0:
            raise MovementExecutionError("max_duration_ms must be positive", field="duration_ms")
        if not math.isfinite(float(max_speed_kmh)) or float(max_speed_kmh) <= 0:
            raise MovementExecutionError("max_speed_kmh must be positive and finite", field="speed_kmh")
        self.dispatcher = dispatcher
        self.track = track
        self._timer_factory = timer_factory
        self._max_duration_ms = int(max_duration_ms)
        self._max_speed_kmh = float(max_speed_kmh)
        self._clock = clock
        self._lock = threading.RLock()
        self._timer: Any | None = None
        self._status = MovementExecutionStatus("idle")
        self._started_at: float | None = None

    @property
    def status(self) -> MovementExecutionStatus:
        with self._lock:
            return self._status

    @property
    def active(self) -> bool:
        return self.status.running

    def start(
        self,
        execution: CoordinateMovementExecutionPlan,
        *,
        confirmed: bool = False,
    ) -> MovementExecutionStatus:
        """Start one request only after explicit caller confirmation."""

        if confirmed is not True:
            raise MovementExecutionError(
                "explicit confirmation is required before coordinate movement",
                field="confirmed",
            )
        if not isinstance(execution, CoordinateMovementExecutionPlan):
            raise MovementExecutionError(
                "a validated coordinate movement execution plan is required",
                field="execution",
            )
        request = execution.request
        with self._lock:
            if self._status.running:
                raise MovementExecutionError("a coordinate movement is already running", field="state")
            self._validate_request(request)
            control = self._register_control(request.train_id)
            if not _is_manual_mode(getattr(control, "mode", "manual")):
                raise MovementExecutionError(
                    "switch the train to manual control before coordinate movement", field="mode"
                )
            if float(getattr(control, "desired_speed", 0.0)) > 0:
                raise MovementExecutionError("the train must be stopped before coordinate movement", field="speed")
            self._validate_track_stopped(request.train_id)

            normalized_speed = request.speed_kmh / self._max_speed_kmh
            self._set_direction(request)
            result = self.dispatcher.manual_speed(request.train_id, normalized_speed)
            if hasattr(result, "accepted") and not result.accepted:
                raise MovementExecutionError(result.detail or "coordinate movement speed was rejected", field="speed")

            self._started_at = self._clock()
            self._status = MovementExecutionStatus("running", request)
            try:
                self._timer = self._timer_factory(request.duration_ms / 1000.0, self._finish)
                if hasattr(self._timer, "daemon"):
                    self._timer.daemon = True
                self._timer.start()
            except Exception as exc:
                self._timer = None
                self._stop_locked(request, error=str(exc))
                raise MovementExecutionError("coordinate movement timer could not start", field="timer") from exc
            return self._status

    def stop(self) -> MovementExecutionStatus:
        """Cancel the timer and stop the active train, if any."""

        with self._lock:
            if not self._status.running or self._status.request is None:
                return self._status
            timer, self._timer = self._timer, None
            if timer is not None and hasattr(timer, "cancel"):
                timer.cancel()
            self._stop_locked(self._status.request)
            return self._status

    execute = start
    cancel = stop

    def close(self) -> None:
        """Stop an active movement before the owning runtime is closed."""

        self.stop()

    def _validate_request(self, request: TimedMovementRequest) -> None:
        if not request.stop_after or request.stop_after_ms != request.duration_ms:
            raise MovementExecutionError("coordinate movement must stop after its duration", field="stop_after")
        if request.duration_ms <= 0 or request.duration_ms > self._max_duration_ms:
            raise MovementExecutionError("movement duration exceeds the executor safety limit", field="duration_ms")
        if request.direction not in {"forward", "reverse"}:
            raise MovementExecutionError("direction must be forward or reverse", field="direction")
        if not math.isfinite(float(request.speed_kmh)) or request.speed_kmh <= 0:
            raise MovementExecutionError("speed must be positive and finite", field="speed_kmh")
        if request.speed_kmh > self._max_speed_kmh:
            raise MovementExecutionError("speed exceeds the executor safety limit", field="speed_kmh")

    def _register_control(self, train_id: str) -> Any:
        register = getattr(self.dispatcher, "register_train", None)
        if register is None:
            raise MovementExecutionError("dispatcher cannot register a train", field="dispatcher")
        return register(train_id)

    def _validate_track_stopped(self, train_id: str) -> None:
        snapshot = self.track.get_snapshot()
        motion = next((item for item in getattr(snapshot, "trains", ()) if item.train_id == train_id), None)
        if motion is not None and (float(motion.speed) > 0 or float(motion.target_speed) > 0):
            raise MovementExecutionError("the train must be stopped before coordinate movement", field="speed")

    def _set_direction(self, request: TimedMovementRequest) -> None:
        desired_forward = request.direction == "forward"
        current_forward = self.track.get_train_direction(request.train_id)
        if current_forward == desired_forward:
            return
        result = self.track.set_train_direction(request.train_id, forward=desired_forward)
        if hasattr(result, "accepted") and not result.accepted:
            raise MovementExecutionError(result.detail or "coordinate movement direction was rejected", field="direction")

    def _finish(self) -> None:
        with self._lock:
            if not self._status.running or self._status.request is None:
                return
            self._timer = None
            self._stop_locked(self._status.request)

    def _stop_locked(self, request: TimedMovementRequest, *, error: str = "") -> None:
        try:
            result = self.track.stop_train(request.train_id)
            if hasattr(result, "accepted") and not result.accepted and not error:
                error = result.detail or "coordinate movement stop was rejected"
            control = self._register_control(request.train_id)
            if hasattr(control, "manual_speed"):
                control.manual_speed = 0.0
            if hasattr(control, "automatic_speed"):
                control.automatic_speed = 0.0
            if hasattr(control, "last_command"):
                control.last_command = "coordinate_move_stop"
            self._status = MovementExecutionStatus("failed" if error else "stopped", request, error)
        except Exception as exc:
            self._status = MovementExecutionStatus("failed", request, error or str(exc))


def _is_manual_mode(mode: object) -> bool:
    return str(getattr(mode, "value", mode)).lower() == "manual"


class CoordinateMovementExecutionPlanner:
    """Validate a coordinate plan and turn it into a bounded movement request.

    Duration is recalculated from the stored calibration record rather than
    trusting a caller-provided timer.  No dispatcher, track, timer, or
    hardware object is used.
    """

    def __init__(self, *, max_duration_ms: int | None = None) -> None:
        if max_duration_ms is not None:
            if isinstance(max_duration_ms, bool):
                raise MovementPlanValidationError(
                    "max_duration_ms must be a whole number", field="execution.max_duration_ms"
                )
            try:
                validated_max_duration = _positive_duration(
                    max_duration_ms, "execution.max_duration_ms"
                )
            except MovementPlanValidationError as exc:
                raise MovementPlanValidationError(
                    str(exc), field="execution.max_duration_ms"
                ) from exc
            if validated_max_duration <= 0:
                raise MovementPlanValidationError(
                    "max_duration_ms must be positive", field="execution.max_duration_ms"
                )
            max_duration_ms = validated_max_duration
        self._max_duration_ms = max_duration_ms

    def validate(
        self,
        movement_plan: CoordinateMovementPlan,
        calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
        *,
        stop_after: bool = True,
    ) -> None:
        """Validate execution inputs without constructing or dispatching a request."""

        self._validated_request(movement_plan, calibration, stop_after=stop_after)

    def build(
        self,
        movement_plan: CoordinateMovementPlan,
        calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
        *,
        stop_after: bool = True,
    ) -> CoordinateMovementExecutionPlan:
        """Build a validated execution plan containing a timed request."""

        request, selected, measured_distance = self._validated_request(
            movement_plan, calibration, stop_after=stop_after
        )
        return CoordinateMovementExecutionPlan(
            movement_plan=movement_plan,
            calibration_speed_kmh=_positive_finite(
                _value(selected, "speed_kmh", "speed"), "calibration.speed_kmh"
            ),
            calibration_duration_ms=_positive_duration(
                _value(selected, "duration_ms", "duration"), "calibration.duration_ms"
            ),
            measured_distance_mm=measured_distance,
            request=request,
        )

    def request(
        self,
        movement_plan: CoordinateMovementPlan,
        calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
        *,
        stop_after: bool = True,
    ) -> TimedMovementRequest:
        """Build only the hardware-neutral timed request."""

        return self.build(movement_plan, calibration, stop_after=stop_after).request

    def _validated_request(
        self,
        movement_plan: CoordinateMovementPlan,
        calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
        *,
        stop_after: bool,
    ) -> tuple[TimedMovementRequest, object, float]:
        if not isinstance(stop_after, bool) or not stop_after:
            raise MovementPlanValidationError(
                "coordinate movement must stop after its duration", field="execution.stop_after"
            )

        train_id = _required_text(_value(movement_plan, "train_id"), "execution.train_id")
        direction = _required_text(
            _value_or_default(movement_plan, "direction", "forward"), "execution.direction"
        ).lower()
        if direction not in {"forward", "reverse"}:
            raise MovementPlanValidationError(
                "execution direction must be 'forward' or 'reverse'", field="execution.direction"
            )
        speed_kmh = _positive_finite(_value(movement_plan, "speed_kmh"), "execution.speed_kmh")
        distance_mm = _finite(_value(movement_plan, "distance_mm"), "execution.distance_mm")
        if distance_mm <= 0:
            raise MovementPlanValidationError(
                "execution distance must be positive", field="execution.distance_mm"
            )

        selected = self._select_calibration(movement_plan, calibration)
        calibration_duration = _positive_duration(
            _value(selected, "duration_ms", "duration"), "calibration.duration_ms"
        )
        measured_distance = _positive_finite(
            _value(selected, "measured_distance_mm", "distance_mm"),
            "calibration.measured_distance_mm",
        )
        try:
            duration_ms = math.ceil(distance_mm * calibration_duration / measured_distance)
        except (OverflowError, ValueError) as exc:
            raise MovementPlanValidationError(
                "execution duration must be finite", field="execution.duration_ms"
            ) from exc
        if duration_ms <= 0:
            raise MovementPlanValidationError(
                "execution duration must be positive", field="execution.duration_ms"
            )
        if self._max_duration_ms is not None and duration_ms > self._max_duration_ms:
            raise MovementPlanValidationError(
                "execution duration exceeds the configured safety limit",
                field="execution.duration_ms",
            )
        return (
            TimedMovementRequest(train_id, direction, speed_kmh, duration_ms, True),
            selected,
            measured_distance,
        )

    @staticmethod
    def _select_calibration(
        movement_plan: CoordinateMovementPlan,
        calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
    ) -> object:
        records = _records(calibration)
        if not records:
            raise MovementPlanValidationError(
                "a stored calibration record is required for execution", field="execution.calibration"
            )
        expected_speed = _positive_finite(
            _value_or_default(movement_plan, "calibration_speed_kmh", _value(movement_plan, "speed_kmh")),
            "execution.calibration_speed_kmh",
        )
        candidates: list[tuple[float, object]] = []
        for record in records:
            try:
                record_speed = _positive_finite(
                    _value(record, "speed_kmh", "speed"), "calibration.speed_kmh"
                )
                _positive_duration(_value(record, "duration_ms", "duration"), "calibration.duration_ms")
                _positive_finite(
                    _value(record, "measured_distance_mm", "distance_mm"),
                    "calibration.measured_distance_mm",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise MovementPlanValidationError(
                    f"invalid stored calibration record: {exc}", field="execution.calibration"
                ) from exc
            candidates.append((abs(record_speed - expected_speed), record))
        return min(candidates, key=lambda item: item[0])[1]


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
            direction=direction,
        )

    def execution_plan(
        self,
        movement_plan: CoordinateMovementPlan,
        *,
        stop_after: bool = True,
        max_duration_ms: int | None = None,
    ) -> CoordinateMovementExecutionPlan:
        """Build a timed execution plan from this planner's stored calibration."""

        return CoordinateMovementExecutionPlanner(max_duration_ms=max_duration_ms).build(
            movement_plan, self._calibrations, stop_after=stop_after
        )

    def timed_request(
        self,
        movement_plan: CoordinateMovementPlan,
        *,
        stop_after: bool = True,
        max_duration_ms: int | None = None,
    ) -> TimedMovementRequest:
        """Build a hardware-neutral timed request from a coordinate plan."""

        return self.execution_plan(
            movement_plan,
            stop_after=stop_after,
            max_duration_ms=max_duration_ms,
        ).request

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


def _value_or_default(value: object, name: str, default: Any) -> Any:
    try:
        return _value(value, name)
    except KeyError:
        return default


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


def _positive_duration(value: Any, field: str) -> int:
    result = _positive_finite(value, field)
    if result != int(result):
        raise MovementPlanValidationError(f"{field} must be a whole number", field=field)
    return int(result)


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


def build_coordinate_movement_execution_plan(
    movement_plan: CoordinateMovementPlan,
    calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
    *,
    stop_after: bool = True,
    max_duration_ms: int | None = None,
) -> CoordinateMovementExecutionPlan:
    """Build a validated, timed execution plan without sending a command."""

    return CoordinateMovementExecutionPlanner(max_duration_ms=max_duration_ms).build(
        movement_plan, calibration, stop_after=stop_after
    )


def build_timed_movement_request(
    movement_plan: CoordinateMovementPlan,
    calibration: Mapping[str, Any] | object | Iterable[Mapping[str, Any] | object],
    *,
    stop_after: bool = True,
    max_duration_ms: int | None = None,
) -> TimedMovementRequest:
    """Build the data-only timed request consumed by a runtime adapter."""

    return build_coordinate_movement_execution_plan(
        movement_plan,
        calibration,
        stop_after=stop_after,
        max_duration_ms=max_duration_ms,
    ).request


# Short aliases keep the request and execution types easy to discover for
# adapters that use generic movement terminology.
MovementRequest = TimedMovementRequest
MovementExecutionPlan = CoordinateMovementExecutionPlan
