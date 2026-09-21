"""Deterministic timetable and schedule simulation service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScheduleEventKind(str, Enum):
    """Events emitted when a timetable stop becomes due."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"


@dataclass(frozen=True)
class ScheduleStop:
    """One train's timed station/platform stop, measured in integer ticks."""

    stop_id: str
    train_id: str
    station_id: str
    arrival_tick: int
    departure_tick: int
    platform_id: str | None = None

    def __post_init__(self) -> None:
        if not self.stop_id or not self.train_id or not self.station_id:
            raise ValueError("stop_id, train_id, and station_id are required")
        if self.arrival_tick < 0 or self.departure_tick < self.arrival_tick:
            raise ValueError("departure_tick must be >= arrival_tick >= 0")


@dataclass(frozen=True)
class ScheduleEvent:
    """A deterministic timetable event."""

    tick: int
    kind: ScheduleEventKind
    stop: ScheduleStop


class TimetableService:
    """Store and advance a timetable without reading the system clock."""

    def __init__(self) -> None:
        self.current_tick = 0
        self.world_current_tick = 0
        self._stops: dict[str, ScheduleStop] = {}
        self._running = False

    @property
    def running(self) -> bool:
        """Whether calls to :meth:`advance` are active."""

        return self._running

    @property
    def stops(self) -> tuple[ScheduleStop, ...]:
        """Return stops in stable timetable order."""

        return tuple(sorted(self._stops.values(), key=self._stop_sort_key))

    def add_stop(self, stop: ScheduleStop) -> None:
        """Insert or replace a stop by stable ID."""

        self._stops[stop.stop_id] = stop

    add_entry = add_stop

    def remove_stop(self, stop_id: str) -> bool:
        """Remove a stop, returning whether it existed."""

        return self._stops.pop(stop_id, None) is not None

    def clear(self) -> None:
        """Remove all stops and reset the current tick."""

        self._stops.clear()
        self.reset()

    def start(self, *, tick: int | None = None, world_tick: int | None = None) -> None:
        """Start advancing from the current tick or explicit schedule/world ticks."""

        if tick is not None:
            if tick < 0:
                raise ValueError("tick cannot be negative")
            self.current_tick = tick
        if world_tick is not None:
            if world_tick < 0:
                raise ValueError("world_tick cannot be negative")
            self.world_current_tick = world_tick
        self._running = True

    def pause(self) -> None:
        """Pause event emission while retaining the current tick."""

        self._running = False

    def reset(self, *, tick: int = 0, world_tick: int | None = None) -> None:
        """Reset time without changing the timetable."""

        if tick < 0:
            raise ValueError("tick cannot be negative")
        if world_tick is not None and world_tick < 0:
            raise ValueError("world_tick cannot be negative")
        self.current_tick = tick
        self.world_current_tick = tick if world_tick is None else world_tick
        self._running = False

    def advance(self, count: int = 1) -> tuple[ScheduleEvent, ...]:
        """Advance exactly ``count`` ticks and emit events in stable order."""

        if count < 0:
            raise ValueError("count cannot be negative")
        if not self._running or count == 0:
            return ()
        previous = self.current_tick
        self.current_tick += count
        return self.events_between(previous, self.current_tick)

    tick = advance

    def advance_world(self, count: int = 1) -> tuple[ScheduleEvent, ...]:
        """Advance the accelerated model-world clock by timetable minutes."""

        if count < 0:
            raise ValueError("count cannot be negative")
        if not self._running or count == 0:
            return ()
        previous = self.world_current_tick
        self.world_current_tick += count
        return self.events_between(previous, self.world_current_tick)

    world_tick = advance_world

    def events_at(self, tick: int) -> tuple[ScheduleEvent, ...]:
        """Return all arrival/departure events exactly at a tick."""

        if tick < 0:
            raise ValueError("tick cannot be negative")
        events: list[ScheduleEvent] = []
        for stop in self._stops.values():
            if stop.arrival_tick == tick:
                events.append(ScheduleEvent(tick, ScheduleEventKind.ARRIVAL, stop))
            if stop.departure_tick == tick:
                events.append(ScheduleEvent(tick, ScheduleEventKind.DEPARTURE, stop))
        return tuple(sorted(events, key=self._event_sort_key))

    def events_between(self, start_exclusive: int, end_inclusive: int) -> tuple[ScheduleEvent, ...]:
        """Return events in ``(start_exclusive, end_inclusive]``."""

        if end_inclusive < start_exclusive:
            raise ValueError("end_inclusive must be >= start_exclusive")
        events = [
            event
            for tick in range(start_exclusive + 1, end_inclusive + 1)
            for event in self.events_at(tick)
        ]
        return tuple(events)

    def simulate_world(self, until_tick: int) -> tuple[ScheduleEvent, ...]:
        """Run the model-world timetable until an absolute world minute."""

        if until_tick < self.world_current_tick:
            raise ValueError("until_tick cannot be before world_current_tick")
        was_running = self._running
        self._running = True
        events = self.advance_world(until_tick - self.world_current_tick)
        self._running = was_running
        return events

    def simulate(self, until_tick: int) -> tuple[ScheduleEvent, ...]:
        """Run a deterministic schedule simulation until an absolute tick."""

        if until_tick < self.current_tick:
            raise ValueError("until_tick cannot be before current_tick")
        was_running = self._running
        self._running = True
        events = self.advance(until_tick - self.current_tick)
        self._running = was_running
        return events

    @staticmethod
    def _stop_sort_key(stop: ScheduleStop) -> tuple[int, int, str, str]:
        return (stop.arrival_tick, stop.departure_tick, stop.train_id, stop.stop_id)

    @classmethod
    def _event_sort_key(cls, event: ScheduleEvent) -> tuple[int, str, int, str]:
        order = 0 if event.kind is ScheduleEventKind.ARRIVAL else 1
        return (event.tick, event.stop.train_id, order, event.stop.stop_id)


Scheduler = TimetableService
