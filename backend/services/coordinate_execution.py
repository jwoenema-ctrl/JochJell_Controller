"""Runtime-owned bounded execution for calibrated coordinate movements."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
from typing import Any, Callable

from .coordinate_move import CoordinateMovementExecutionPlan, TimedMovementRequest


class CoordinateExecutionError(ValueError):
    """A coordinate movement cannot be safely started or stopped."""


@dataclass(frozen=True)
class CoordinateExecutionStatus:
    train_id: str
    state: str
    direction: str
    speed_kmh: float
    duration_ms: int
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"train_id": self.train_id, "state": self.state, "direction": self.direction,
                "speed_kmh": self.speed_kmh, "duration_ms": self.duration_ms, "detail": self.detail}


class CoordinateMovementExecutor:
    """Execute one finite movement at a time and always issue a stop."""

    def __init__(
        self,
        dispatcher: Any,
        track: Any,
        *,
        on_status: Callable[[CoordinateExecutionStatus], None] | None = None,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
        max_duration_ms: int = 120_000,
        max_speed_kmh: float = 140.0,
    ) -> None:
        self._init(
            dispatcher,
            track,
            on_status=on_status,
            timer_factory=timer_factory,
            max_duration_ms=max_duration_ms,
            max_speed_kmh=max_speed_kmh,
        )

    def _init(
        self,
        dispatcher: Any,
        track: Any,
        *,
        on_status: Callable[[CoordinateExecutionStatus], None] | None = None,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
        max_duration_ms: int = 120_000,
        max_speed_kmh: float = 140.0,
    ) -> None:
        try:
            valid_duration = not isinstance(max_duration_ms, bool) and int(max_duration_ms) == max_duration_ms and max_duration_ms > 0
        except (TypeError, ValueError, OverflowError):
            valid_duration = False
        if not valid_duration:
            raise CoordinateExecutionError("max_duration_ms must be a positive whole number")
        if not math.isfinite(float(max_speed_kmh)) or float(max_speed_kmh) <= 0:
            raise CoordinateExecutionError("max_speed_kmh must be positive and finite")
        self._dispatcher = dispatcher
        self._track = track
        self._on_status = on_status
        self._timer_factory = timer_factory
        self._max_duration_ms = int(max_duration_ms)
        self._max_speed_kmh = float(max_speed_kmh)
        self._lock = threading.RLock()
        self._timer: Any | None = None
        self._status: CoordinateExecutionStatus | None = None

    @property
    def status(self) -> CoordinateExecutionStatus | None:
        with self._lock:
            return self._status

    def start(
        self,
        request: TimedMovementRequest | CoordinateMovementExecutionPlan,
        *,
        normalized_speed: float | None = None,
        confirmed: bool = False,
    ) -> CoordinateExecutionStatus:
        if confirmed is not True:
            raise CoordinateExecutionError("explicit confirmation is required before coordinate movement")
        if isinstance(request, CoordinateMovementExecutionPlan):
            request = request.request
        if not isinstance(request, TimedMovementRequest):
            raise CoordinateExecutionError("a validated timed movement request is required")
        self._validate_request(request)
        expected_normalized_speed = request.speed_kmh / self._max_speed_kmh
        if normalized_speed is None:
            normalized_speed = expected_normalized_speed
        if not 0 < float(normalized_speed) <= 1 or not math.isclose(
            float(normalized_speed), expected_normalized_speed, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise CoordinateExecutionError("normalized movement speed does not match the calibrated request")
        with self._lock:
            if self._status is not None and self._status.state == "running":
                raise CoordinateExecutionError("a coordinate movement is already active")
            control = self._dispatcher.register_train(request.train_id)
            if str(getattr(getattr(control, "mode", None), "value", getattr(control, "mode", ""))).lower() != "manual":
                raise CoordinateExecutionError("coordinate movement requires manual control")
            if float(getattr(control, "desired_speed", 0.0)) > 0:
                raise CoordinateExecutionError("the train must be stopped before coordinate movement")
            snapshot = self._track.get_snapshot()
            motion = next((item for item in getattr(snapshot, "trains", ()) if item.train_id == request.train_id), None)
            if motion is not None and (float(motion.speed) > 0 or float(motion.target_speed) > 0):
                raise CoordinateExecutionError("the train must be stopped before coordinate movement")
            if self._track.get_train_direction(request.train_id) != (request.direction == "forward"):
                direction_result = self._track.set_train_direction(
                    request.train_id, forward=request.direction == "forward"
                )
                if hasattr(direction_result, "accepted") and not direction_result.accepted:
                    raise CoordinateExecutionError(direction_result.detail or "train direction was rejected")
            speed_result = self._dispatcher.manual_speed(request.train_id, float(normalized_speed))
            if hasattr(speed_result, "accepted") and not speed_result.accepted:
                raise CoordinateExecutionError(speed_result.detail or "movement speed was rejected")
            status = CoordinateExecutionStatus(request.train_id, "running", request.direction, request.speed_kmh, request.duration_ms)
            self._status = status
            self._publish(status)
            try:
                self._timer = self._timer_factory(request.duration_ms / 1000.0, lambda: self._finish(request.train_id))
                if hasattr(self._timer, "daemon"):
                    self._timer.daemon = True
                self._timer.start()
            except Exception as exc:
                self._timer = None
                self._stop_locked(request.train_id, detail=str(exc), final_state="failed")
                raise CoordinateExecutionError("coordinate movement timer could not start") from exc
            return status

    def stop(self, train_id: str, *, detail: str = "stopped") -> CoordinateExecutionStatus | None:
        with self._lock:
            if self._status is None or self._status.train_id != train_id:
                return None
            if self._timer is not None:
                if hasattr(self._timer, "cancel"):
                    self._timer.cancel()
            self._timer = None
            self._stop_locked(train_id, detail=detail, final_state="stopped")
            return self._status

    def close(self) -> None:
        with self._lock:
            train_id = self._status.train_id if self._status and self._status.state == "running" else None
        if train_id:
            self.stop(train_id, detail="runtime closed")

    def _finish(self, train_id: str) -> None:
        with self._lock:
            if self._status is None or self._status.train_id != train_id or self._status.state != "running":
                return
            self._timer = None
            self._stop_locked(train_id, detail="movement timer elapsed; train stopped", final_state="completed")

    def _validate_request(self, request: TimedMovementRequest) -> None:
        if request.direction not in {"forward", "reverse"}:
            raise CoordinateExecutionError("direction must be forward or reverse")
        if not request.stop_after or request.stop_after_ms != request.duration_ms:
            raise CoordinateExecutionError("coordinate movement must stop after its duration")
        if not isinstance(request.duration_ms, int) or request.duration_ms <= 0 or request.duration_ms > self._max_duration_ms:
            raise CoordinateExecutionError("movement duration exceeds the executor safety limit")
        if not math.isfinite(float(request.speed_kmh)) or request.speed_kmh <= 0 or request.speed_kmh > self._max_speed_kmh:
            raise CoordinateExecutionError("movement speed exceeds the executor safety limit")

    def _stop_locked(self, train_id: str, *, detail: str, final_state: str) -> None:
        previous = self._status
        if previous is None:
            return
        error = detail if final_state == "failed" else ""
        try:
            result = self._track.stop_train(train_id)
            if hasattr(result, "accepted") and not result.accepted:
                error = result.detail or "train stop was rejected"
                final_state = "failed"
            control = self._dispatcher.register_train(train_id)
            if hasattr(control, "manual_speed"):
                control.manual_speed = 0.0
            if hasattr(control, "automatic_speed"):
                control.automatic_speed = 0.0
            if hasattr(control, "last_command"):
                control.last_command = "coordinate_move_stop"
        except Exception as exc:
            error = str(exc)
            final_state = "failed"
        status = CoordinateExecutionStatus(previous.train_id, final_state, previous.direction, previous.speed_kmh, previous.duration_ms, error or detail)
        self._status = status
        self._publish(status)

    def _publish(self, status: CoordinateExecutionStatus) -> None:
        if self._on_status is not None:
            try:
                self._on_status(status)
            except Exception:
                # Status observers must never prevent the safety stop or timer
                # lifecycle from completing.
                pass
