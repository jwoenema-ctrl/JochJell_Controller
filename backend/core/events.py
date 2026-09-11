"""Typed, in-process domain events.

The event controller is intentionally small: it provides ordered publication
and type-filtered subscriptions without deciding how events are persisted or
transported.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import Callable, TypeVar

from .models import BlockState, ScheduleStatus, SignalAspect, TrainMode, TurnoutPosition


@dataclass(frozen=True, slots=True)
class Event:
    """Base class for all domain events."""

    sequence: int = 0


@dataclass(frozen=True, slots=True)
class LayoutChanged(Event):
    """Published when a complete layout snapshot is committed."""

    revision: int = 0


@dataclass(frozen=True, slots=True)
class BlockStateChanged(Event):
    """Published when block occupancy or availability changes."""

    block_id: str = ""
    state: BlockState = BlockState.FREE
    occupied_by: str | None = None


@dataclass(frozen=True, slots=True)
class TurnoutPositionChanged(Event):
    """Published when a turnout selects a different branch."""

    turnout_id: str = ""
    position: TurnoutPosition = TurnoutPosition.UNKNOWN


@dataclass(frozen=True, slots=True)
class SignalAspectChanged(Event):
    """Published when a signal aspect changes."""

    signal_id: str = ""
    aspect: SignalAspect = SignalAspect.RED


@dataclass(frozen=True, slots=True)
class TrainPositionChanged(Event):
    """Published when a train changes its current block."""

    train_id: str = ""
    from_block_id: str | None = None
    to_block_id: str | None = None


@dataclass(frozen=True, slots=True)
class TrainSpeedChanged(Event):
    """Published when a train's commanded speed changes."""

    train_id: str = ""
    speed_kmh: float = 0.0
    mode: TrainMode = TrainMode.MANUAL


@dataclass(frozen=True, slots=True)
class TrainModeChanged(Event):
    """Published when manual, automatic, or stopped control is selected."""

    train_id: str = ""
    mode: TrainMode = TrainMode.MANUAL


@dataclass(frozen=True, slots=True)
class RouteChanged(Event):
    """Published when the dispatcher or planner changes a train route."""

    train_id: str = ""
    route: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrackPowerChanged(Event):
    """Published when the track voltage command changes."""

    enabled: bool = True


@dataclass(frozen=True, slots=True)
class FeedbackHealthChanged(Event):
    """Published when configured physical occupancy feedback changes health."""

    healthy: bool = True
    error: str = ""


@dataclass(frozen=True, slots=True)
class TrainDatabaseChanged(Event):
    """Published when persisted train metadata or a related record changes."""

    train_id: str = ""
    entity: str = "train"
    action: str = "updated"
    record_id: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleStateChanged(Event):
    """Published when a schedule changes lifecycle state."""

    schedule_id: str = ""
    status: ScheduleStatus = ScheduleStatus.PLANNED


EventHandler = Callable[[Event], None]
_EventT = TypeVar("_EventT", bound=Event)


class EventSubscription:
    """A removable event handler registration."""

    def __init__(self, controller: "EventController", token: int) -> None:
        self._controller = controller
        self._token = token
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether this subscription has been removed."""

        return self._closed

    def close(self) -> None:
        """Remove the handler; repeated calls are safe."""

        if not self._closed:
            self._controller._unsubscribe(self._token)
            self._closed = True

    def __enter__(self) -> "EventSubscription":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class EventController:
    """Thread-safe event publisher with stable registration order."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sequence = 0
        self._next_token = 1
        self._handlers: dict[int, tuple[type[Event], EventHandler]] = {}

    def subscribe(
        self,
        event_type: type[_EventT],
        handler: Callable[[_EventT], None],
    ) -> EventSubscription:
        """Register ``handler`` for ``event_type`` and its subclasses."""

        if not isinstance(event_type, type) or not issubclass(event_type, Event):
            raise TypeError("event_type must be an Event subclass")
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._handlers[token] = (event_type, handler)  # type: ignore[assignment]
        return EventSubscription(self, token)

    def _unsubscribe(self, token: int) -> None:
        with self._lock:
            self._handlers.pop(token, None)

    def publish(self, event: _EventT) -> _EventT:
        """Assign a sequence number, then deliver an event to matching handlers."""

        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        with self._lock:
            self._sequence += 1
            published = replace(event, sequence=self._sequence)
            handlers = tuple(self._handlers.values())
        first_error: Exception | None = None
        for event_type, handler in handlers:
            if isinstance(published, event_type):
                try:
                    handler(published)
                except Exception as error:  # Complete the dispatch before surfacing the first failure.
                    if first_error is None:
                        first_error = error
        if first_error is not None:
            raise first_error
        return published

    emit = publish
