"""Dependency-free recording and playback plans for train automation.

The service intentionally stops at producing a validated, immutable plan.  A
caller can hand that plan to a dispatcher or a future playback runner without
giving this module any knowledge of transport, HTTP, or UI concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from numbers import Real
from typing import Any, Mapping


class ActionOperation(str, Enum):
    """Operations that can be recorded for one train."""

    SPEED = "speed"
    DIRECTION = "direction"
    FUNCTION = "function"


@dataclass(frozen=True)
class RecordedAction:
    """One validated train command at a timestamp.

    ``speed`` is the normalized controller speed in the inclusive range
    0..1.  Direction is represented as ``"forward"`` or ``"reverse"`` and
    decoder functions use DCC function numbers 0..31.

    Only the payload matching ``operation`` may be supplied.  ``train_id`` is
    optional while constructing an action so the recorder can attach the ID
    of its active recording; plans always contain actions with a train ID.
    """

    timestamp: float
    operation: ActionOperation | str
    train_id: str = ""
    speed: float | None = None
    direction: str | None = None
    function_number: int | None = None
    enabled: bool | None = None

    def __post_init__(self) -> None:
        timestamp = _finite_number(self.timestamp, "timestamp")
        if timestamp < 0:
            raise ValueError("timestamp cannot be negative")
        object.__setattr__(self, "timestamp", timestamp)

        operation = _operation(self.operation)
        object.__setattr__(self, "operation", operation)

        if not isinstance(self.train_id, str):
            raise ValueError("train_id must be a string")
        if self.train_id and not self.train_id.strip():
            raise ValueError("train_id cannot be blank")

        if operation == ActionOperation.SPEED.value:
            if self.speed is None or self.direction is not None or self.function_number is not None or self.enabled is not None:
                raise ValueError("speed actions require only speed")
            speed = _finite_number(self.speed, "speed")
            if not 0.0 <= speed <= 1.0:
                raise ValueError("speed must be between 0 and 1")
            object.__setattr__(self, "speed", speed)
        elif operation == ActionOperation.DIRECTION.value:
            if self.direction not in {"forward", "reverse"} or self.speed is not None or self.function_number is not None or self.enabled is not None:
                raise ValueError("direction actions require forward or reverse direction only")
        else:
            if self.function_number is None or not isinstance(self.function_number, int) or isinstance(self.function_number, bool):
                raise ValueError("function_number must be an integer")
            if not 0 <= self.function_number <= 31:
                raise ValueError("function_number must be between 0 and 31")
            if not isinstance(self.enabled, bool) or self.speed is not None or self.direction is not None:
                raise ValueError("function actions require function_number and boolean enabled")

    @property
    def kind(self) -> str:
        """Compatibility-friendly name for the operation kind."""

        return self.operation

    @property
    def value(self) -> float | str | bool:
        """Return the operation's single playback value."""

        if self.operation == ActionOperation.SPEED.value:
            return self.speed  # type: ignore[return-value]
        if self.operation == ActionOperation.DIRECTION.value:
            return self.direction  # type: ignore[return-value]
        return self.enabled  # type: ignore[return-value]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        train_id: str = "",
        timestamp: float | None = None,
    ) -> "RecordedAction":
        """Parse and validate a JSON-shaped action mapping.

        The parser accepts ``operation``, ``kind``, or ``type`` as the
        operation key and supports ``value`` as a shorthand for the operation
        payload.  This keeps the service useful at API boundaries while still
        rejecting unknown or incomplete action shapes.
        """

        if not isinstance(payload, Mapping):
            raise ValueError("action must be an object")

        operation_value = _first(payload, "operation", "kind", "type", "action")
        if operation_value is None:
            raise ValueError("action operation is required")
        operation = _operation(operation_value)

        raw_train_id = payload.get("train_id", train_id)
        raw_timestamp = payload.get("timestamp", timestamp)
        if raw_timestamp is None:
            raise ValueError("action timestamp is required")

        allowed = {
            "operation", "kind", "type", "action", "train_id", "timestamp", "value",
            "speed", "direction", "function_number", "function", "number", "enabled",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown action field(s): {', '.join(sorted(map(str, unknown)))}")

        if operation == ActionOperation.SPEED.value:
            value = _payload_value(payload, "speed")
            return cls(timestamp=raw_timestamp, operation=operation, train_id=raw_train_id, speed=value)
        if operation == ActionOperation.DIRECTION.value:
            value = _payload_value(payload, "direction")
            if value not in {"forward", "reverse"}:
                raise ValueError("direction must be forward or reverse")
            return cls(timestamp=raw_timestamp, operation=operation, train_id=raw_train_id, direction=value)

        function_number = _first(payload, "function_number", "function", "number")
        enabled = payload.get("enabled", payload.get("value"))
        return cls(
            timestamp=raw_timestamp,
            operation=operation,
            train_id=raw_train_id,
            function_number=function_number,
            enabled=enabled,
        )


@dataclass(frozen=True)
class PlaybackPlan:
    """Immutable sequence of actions ready for a playback consumer."""

    train_id: str
    actions: tuple[RecordedAction, ...]
    started_at: float
    stopped_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.train_id, str) or not self.train_id.strip():
            raise ValueError("train_id is required")
        actions = tuple(self.actions)
        previous = self.started_at
        for action in actions:
            if not isinstance(action, RecordedAction):
                raise ValueError("playback plan actions must be RecordedAction instances")
            if action.train_id != self.train_id:
                raise ValueError("action train_id does not match playback plan")
            if action.timestamp < previous:
                raise ValueError("action timestamps must be nondecreasing")
            previous = action.timestamp
        started_at = _finite_number(self.started_at, "started_at")
        stopped_at = _finite_number(self.stopped_at, "stopped_at")
        if started_at < 0 or stopped_at < started_at or stopped_at < previous:
            raise ValueError("playback timestamps must be nondecreasing")
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "stopped_at", stopped_at)

    @property
    def duration(self) -> float:
        return self.stopped_at - self.started_at

    @property
    def action_count(self) -> int:
        return len(self.actions)

    @property
    def start_timestamp(self) -> float:
        return self.started_at

    @property
    def stop_timestamp(self) -> float:
        return self.stopped_at


class AutomationRecordingService:
    """Record one train's validated actions into an immutable playback plan."""

    def __init__(self) -> None:
        self._train_id: str | None = None
        self._started_at: float | None = None
        self._actions: list[RecordedAction] = []

    @property
    def active(self) -> bool:
        return self._train_id is not None

    @property
    def recording(self) -> bool:
        return self.active

    @property
    def train_id(self) -> str | None:
        return self._train_id

    @property
    def actions(self) -> tuple[RecordedAction, ...]:
        return tuple(self._actions)

    def start(self, train_id: str, *, timestamp: float = 0.0) -> None:
        """Start a fresh recording for ``train_id``."""

        if self.active:
            raise ValueError("a recording is already active")
        if not isinstance(train_id, str) or not train_id.strip():
            raise ValueError("train_id is required")
        self._started_at = _finite_number(timestamp, "timestamp")
        if self._started_at < 0:
            raise ValueError("timestamp cannot be negative")
        self._train_id = train_id
        self._actions = []

    def append(self, action: RecordedAction | Mapping[str, Any], timestamp: float | None = None) -> RecordedAction:
        """Validate and append one action to the active recording."""

        if not self.active or self._started_at is None:
            raise ValueError("start a recording before appending actions")
        if isinstance(action, RecordedAction):
            if timestamp is not None:
                raise ValueError("timestamp cannot be supplied twice")
            parsed = action
        else:
            parsed = RecordedAction.from_mapping(action, train_id=self._train_id or "", timestamp=timestamp)
        if parsed.train_id and parsed.train_id != self._train_id:
            raise ValueError("action train_id does not match active recording")
        parsed = replace(parsed, train_id=self._train_id)
        previous = self._actions[-1].timestamp if self._actions else self._started_at
        if parsed.timestamp < previous:
            raise ValueError("action timestamp cannot precede the previous action")
        self._actions.append(parsed)
        return parsed

    def stop(self, *, timestamp: float | None = None) -> PlaybackPlan:
        """Stop recording and return an immutable playback plan."""

        if not self.active or self._started_at is None or self._train_id is None:
            raise ValueError("no recording is active")
        stopped_at = self._actions[-1].timestamp if timestamp is None and self._actions else timestamp
        if stopped_at is None:
            stopped_at = self._started_at
        stopped_at = _finite_number(stopped_at, "timestamp")
        previous = self._actions[-1].timestamp if self._actions else self._started_at
        if stopped_at < previous:
            raise ValueError("stop timestamp cannot precede the previous action")
        plan = PlaybackPlan(self._train_id, tuple(self._actions), self._started_at, stopped_at)
        self._train_id = None
        self._started_at = None
        self._actions = []
        return plan


def validate_action(action: RecordedAction | Mapping[str, Any], *, train_id: str = "") -> RecordedAction:
    """Validate an action without changing recorder state."""

    if isinstance(action, RecordedAction):
        if train_id and action.train_id and action.train_id != train_id:
            raise ValueError("action train_id does not match requested train")
        return action
    return RecordedAction.from_mapping(action, train_id=train_id)


def _operation(value: object) -> str:
    if isinstance(value, ActionOperation):
        return value.value
    if not isinstance(value, str) or value not in {item.value for item in ActionOperation}:
        raise ValueError("operation must be speed, direction, or function")
    return value


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _first(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def _payload_value(payload: Mapping[str, Any], field: str) -> Any:
    value = payload.get(field, payload.get("value"))
    if value is None:
        raise ValueError(f"{field} action value is required")
    return value


# Short aliases make the service easy to discover without duplicating logic.
AutomationRecorder = AutomationRecordingService
AutomationAction = RecordedAction


__all__ = [
    "ActionOperation",
    "AutomationAction",
    "AutomationRecorder",
    "AutomationRecordingService",
    "PlaybackPlan",
    "RecordedAction",
    "validate_action",
]
