"""Measured train movement calibration for real and simulated track adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable

from backend.infrastructure.interfaces import CommandResult
from .dispatcher import ControlMode


@dataclass(frozen=True)
class CalibrationRun:
    """The short movement test currently known to the controller."""

    run_id: str
    train_id: str
    speed_kmh: float
    duration_ms: int
    status: str = "idle"
    started_at: str | None = None
    stopped_at: str | None = None
    error: str = ""


class TrainCalibrationService:
    """Run a bounded 10 km/h movement test and store its measurement.

    The service deliberately owns the timer and stop operation. This prevents a
    browser tab or a delayed HTTP response from being responsible for sending
    the safety stop packet.
    """

    def __init__(
        self,
        dispatcher: Any,
        track: Any,
        database: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], str] | None = None,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
    ) -> None:
        self.dispatcher = dispatcher
        self.track = track
        self.database = database
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())
        self._timer_factory = timer_factory
        self._lock = threading.RLock()
        self._run: CalibrationRun | None = None
        self._timer: Any | None = None
        self._sequence = 0

    @property
    def run(self) -> CalibrationRun | None:
        with self._lock:
            return self._run

    def start(self, train_id: str, *, speed_kmh: float = 10.0, duration_ms: int = 100) -> CalibrationRun:
        speed_kmh = float(speed_kmh)
        duration_ms = int(duration_ms)
        if speed_kmh <= 0 or duration_ms <= 0 or duration_ms > 1000:
            raise ValueError("calibration speed must be positive and duration must be between 1 and 1000 ms")
        with self._lock:
            if self._run is not None and self._run.status == "running":
                raise ValueError("a calibration run is already active")
            control = self.dispatcher.register_train(train_id)
            if control.mode is ControlMode.AUTOMATIC:
                raise ValueError("switch the train to manual control before calibration")
            if control.desired_speed > 0:
                raise ValueError("the train must be stopped before calibration")
            control.mode = ControlMode.MANUAL
            maximum = max(1.0, float(getattr(self, "_max_speed_kmh", 140.0)))
            result = self.dispatcher.manual_speed(train_id, min(1.0, speed_kmh / maximum))
            if hasattr(result, "accepted") and not result.accepted:
                raise ValueError(result.detail or "calibration movement was rejected")
            self._sequence += 1
            run_id = f"cal-{self._sequence}"
            started = self._now()
            self._run = CalibrationRun(run_id, train_id, speed_kmh, duration_ms, "running", started_at=started)
            self._timer = self._timer_factory(duration_ms / 1000.0, lambda: self._finish(run_id))
            self._timer.daemon = True
            self._timer.start()
            return self._run

    def set_max_speed(self, max_speed_kmh: float) -> None:
        self._max_speed_kmh = max(1.0, float(max_speed_kmh))

    def _finish(self, run_id: str) -> None:
        with self._lock:
            if self._run is None or self._run.run_id != run_id or self._run.status != "running":
                return
            train_id = self._run.train_id
            try:
                result = self.track.stop_train(train_id)
                if hasattr(result, "accepted") and not result.accepted:
                    raise RuntimeError(result.detail or "calibration stop was rejected")
                control = self.dispatcher.register_train(train_id)
                control.manual_speed = control.automatic_speed = 0.0
                self._run = CalibrationRun(
                    self._run.run_id, train_id, self._run.speed_kmh, self._run.duration_ms,
                    "completed", self._run.started_at, self._now(),
                )
            except Exception as exc:
                self._run = CalibrationRun(
                    self._run.run_id, train_id, self._run.speed_kmh, self._run.duration_ms,
                    "failed", self._run.started_at, self._now(), str(exc),
                )
            finally:
                self._timer = None

    def cancel(self) -> CalibrationRun | None:
        with self._lock:
            if self._run is None or self._run.status != "running":
                return self._run
            timer, self._timer = self._timer, None
            if timer is not None:
                timer.cancel()
            self.track.stop_train(self._run.train_id)
            control = self.dispatcher.register_train(self._run.train_id)
            control.manual_speed = control.automatic_speed = 0.0
            self._run = CalibrationRun(
                self._run.run_id, self._run.train_id, self._run.speed_kmh, self._run.duration_ms,
                "cancelled", self._run.started_at, self._now(),
            )
            return self._run

    def record_distance(self, distance_mm: float, *, notes: str = "") -> Any:
        with self._lock:
            if self._run is None or self._run.status != "completed":
                raise ValueError("complete a calibration run before recording distance")
            distance_mm = float(distance_mm)
            if distance_mm < 0:
                raise ValueError("distance cannot be negative")
            record = self.database.add_calibration(
                self._run.train_id,
                speed_kmh=self._run.speed_kmh,
                duration_ms=self._run.duration_ms,
                measured_distance_mm=distance_mm,
                notes=notes,
                created_at=self._run.stopped_at or self._now(),
            )
            self._run = CalibrationRun(
                self._run.run_id, self._run.train_id, self._run.speed_kmh, self._run.duration_ms,
                "recorded", self._run.started_at, self._run.stopped_at,
            )
            return record

    def history(self, train_id: str | None = None) -> tuple[Any, ...]:
        return self.database.list_calibrations(train_id)

    def close(self) -> None:
        self.cancel()
