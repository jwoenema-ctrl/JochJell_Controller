"""Deterministic, hardware-free track system for development and testing."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Iterable, Mapping, Sequence

from .interfaces import CommandResult, TrackSnapshot, TrainMotion
from backend.services.connection_speed import ConnectionSpeedPolicy, next_connection


@dataclass
class _Train:
    """Mutable internal representation of a simulated train."""

    train_id: str
    block_id: str
    position: float
    speed: float
    commanded_speed: float
    target_speed: float
    direction: int
    route: tuple[str, ...]
    route_index: int


@dataclass
class _Signal:
    """Mutable signal state used only by the deterministic simulator."""

    signal_id: str
    protects_block_id: str
    aspect: str


@dataclass(frozen=True)
class _SafetyBoundary:
    """The next point a train must not pass during the current tick."""

    distance: float
    reason: str
    block_id: str


class SimulatedTrackSystem:
    """A fixed-step track model with no wall-clock or network dependency.

    A train moves one normalized block length per distance unit.  The caller
    controls time exclusively through :meth:`tick`, making snapshots repeatable
    in tests and in schedule simulations.  Automatic motion retains its
    commanded speed, while the safety layer derives a lower effective target
    whenever occupancy, authority, or a restrictive signal requires an
    approach or stop.
    """

    _BOUNDARY_EPSILON = 1e-6
    _RESTRICTIVE_SIGNAL_ASPECTS = frozenset({"red", "stop", "danger", "off"})
    _CLEAR_SIGNAL_ASPECTS = frozenset({"green", "shunting"})

    def __init__(
        self,
        *,
        tick_seconds: float = 0.1,
        acceleration: float = 1.0,
        blocks: Iterable[str] = (),
    ) -> None:
        if tick_seconds <= 0:
            raise ValueError("tick_seconds must be positive")
        if acceleration <= 0:
            raise ValueError("acceleration must be positive")
        self.tick_seconds = float(tick_seconds)
        self.acceleration = float(acceleration)
        self._blocks = set(blocks)
        self._trains: dict[str, _Train] = {}
        self._authorities: dict[str, tuple[str, ...]] = {}
        self._signals: dict[str, _Signal] = {}
        self._turnouts: dict[str, int] = {}
        self._powered = True
        self._tick = 0
        self._lock = RLock()
        self._speed_policy = ConnectionSpeedPolicy()

    def configure_speed_limits(self, policy: ConnectionSpeedPolicy) -> None:
        with self._lock:
            self._speed_policy = policy
            self._refresh_safety_targets()

    def _connection_limit(self, train: _Train) -> float:
        return self._speed_policy.normalized_limit(train.train_id,
            next_connection(train.block_id, train.route, train.direction))

    def get_train_speed_limit(self, train_id: str) -> float | None:
        with self._lock:
            train = self._trains.get(train_id)
            return self._speed_policy.limit_kmh(train_id,
                next_connection(train.block_id, train.route, train.direction)) if train else None

    def rename_block(self, old: str, new: str) -> None:
        """Rename without resetting train position, direction or speed."""
        with self._lock:
            self._blocks.discard(old)
            self._blocks.add(new)
            for train in self._trains.values():
                if train.block_id == old:
                    train.block_id = new
                train.route = tuple(new if item == old else item for item in train.route)
            self._authorities = {key: tuple(new if item == old else item for item in route)
                                 for key, route in self._authorities.items()}
            for signal in self._signals.values():
                if signal.protects_block_id == old:
                    signal.protects_block_id = new

    def add_block(self, block_id: str) -> None:
        """Register a block name for occupancy validation and display."""

        if not block_id:
            raise ValueError("block_id is required")
        with self._lock:
            self._blocks.add(block_id)

    def add_train(
        self,
        train_id: str,
        block_id: str,
        *,
        route: Sequence[str] = (),
        speed: float = 0.0,
        direction: int = 1,
    ) -> CommandResult:
        """Place a train in a block, optionally with its ordered route."""

        self._validate_speed(speed)
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        if not train_id or not block_id:
            raise ValueError("train_id and block_id are required")
        with self._lock:
            if train_id in self._trains:
                return CommandResult(False, "add_train", "train already exists")
            self._blocks.add(block_id)
            route_tuple = self._normalise_route(block_id, route)
            self._trains[train_id] = _Train(
                train_id=train_id,
                block_id=block_id,
                position=0.0,
                speed=float(speed),
                commanded_speed=float(speed),
                target_speed=float(speed),
                direction=direction,
                route=route_tuple,
                route_index=route_tuple.index(block_id),
            )
            self._refresh_safety_targets()
        return CommandResult(True, "add_train", "train added")

    def remove_train(self, train_id: str) -> CommandResult:
        """Remove a train from the simulated layout."""

        with self._lock:
            if self._trains.pop(train_id, None) is None:
                return CommandResult(False, "remove_train", "unknown train")
            self._authorities.pop(train_id, None)
            self._refresh_safety_targets()
        return CommandResult(True, "remove_train", "train removed")

    def set_train_route(self, train_id: str, route: Sequence[str]) -> CommandResult:
        """Replace a train's route while retaining its current block."""

        with self._lock:
            train = self._trains.get(train_id)
            if train is None:
                return CommandResult(False, "set_train_route", "unknown train")
            route_tuple = self._normalise_route(train.block_id, route)
            train.route = route_tuple
            train.route_index = route_tuple.index(train.block_id)
            self._refresh_safety_targets()
        return CommandResult(True, "set_train_route", "route updated")

    def set_train_speed(self, train_id: str, speed: float) -> CommandResult:
        """Set a normalized target speed in the inclusive range 0..1."""

        self._validate_speed(speed)
        with self._lock:
            train = self._trains.get(train_id)
            if train is None:
                return CommandResult(False, "set_train_speed", "unknown train")
            train.commanded_speed = float(speed)
            self._refresh_safety_targets()
        return CommandResult(True, "set_train_speed", "target speed updated")

    def get_train_direction(self, train_id: str) -> bool:
        with self._lock:
            train = self._trains.get(train_id)
            return train.direction == 1 if train else True

    def set_train_direction(self, train_id: str, *, forward: bool) -> CommandResult:
        with self._lock:
            train = self._trains.get(train_id)
            if train is None:
                return CommandResult(False, "set_direction", "unknown train")
            if train.speed > 0 or train.target_speed > 0 or train.commanded_speed > 0:
                return CommandResult(False, "set_direction", "stop the train before changing direction")
            train.direction = 1 if forward else -1
            self._refresh_safety_targets()
            return CommandResult(True, "set_direction", "direction updated")

    def stop_train(self, train_id: str) -> CommandResult:
        """Set one train's target speed to zero."""

        return self.set_train_speed(train_id, 0.0)

    def set_power(self, enabled: bool) -> CommandResult:
        """Switch simulated track power on or off."""

        with self._lock:
            self._powered = bool(enabled)
            if not self._powered:
                for train in self._trains.values():
                    train.target_speed = 0.0
            else:
                self._refresh_safety_targets()
        return CommandResult(True, "set_power", "track power updated")

    def set_authority(
        self,
        train_id: str,
        allowed_route: Sequence[str] | str | None,
    ) -> CommandResult:
        """Set the blocks a train may enter, or clear its authority limit.

        ``allowed_route`` is a safe route prefix, including the train's
        current block when convenient.  An empty route is an explicit stop at
        the next boundary.  Passing ``None`` removes the limit and restores
        the simulator's historical route-only behavior.
        """

        with self._lock:
            if train_id not in self._trains:
                return CommandResult(False, "set_authority", "unknown train")
            if allowed_route is None:
                self._authorities.pop(train_id, None)
            else:
                values = (
                    (allowed_route.strip(),)
                    if isinstance(allowed_route, str) and allowed_route.strip()
                    else tuple(dict.fromkeys(str(item).strip() for item in allowed_route if str(item).strip()))
                )
                self._blocks.update(values)
                self._authorities[train_id] = values
            self._refresh_safety_targets()
        return CommandResult(True, "set_authority", "movement authority updated")

    set_movement_authority = set_authority

    def clear_authority(self, train_id: str) -> CommandResult:
        """Remove an explicit authority limit for one train."""

        return self.set_authority(train_id, None)

    def set_signal(
        self,
        signal_id: str,
        aspect: str,
        *,
        protects_block_id: str | None = None,
    ) -> CommandResult:
        """Set a simulated signal and its protected block.

        Signals are deliberately local to the simulator: restrictive aspects
        create a safe boundary before ``protects_block_id``.  A signal first
        registered with a block can subsequently be updated by aspect only.
        Green and shunting are clear; red, stop, danger, and off are
        restrictive.  Yellow is accepted as an approach aspect and does not
        itself deny entry to the protected block.
        """

        selected_id = str(signal_id).strip()
        selected_aspect = str(getattr(aspect, "value", aspect)).strip().lower()
        if not selected_id:
            raise ValueError("signal_id is required")
        if selected_aspect not in self._RESTRICTIVE_SIGNAL_ASPECTS | self._CLEAR_SIGNAL_ASPECTS | {"yellow"}:
            raise ValueError("unsupported signal aspect")
        with self._lock:
            existing = self._signals.get(selected_id)
            protected = str(protects_block_id).strip() if protects_block_id is not None else (
                existing.protects_block_id if existing is not None else ""
            )
            if not protected:
                raise ValueError("protects_block_id is required for a new signal")
            self._blocks.add(protected)
            self._signals[selected_id] = _Signal(selected_id, protected, selected_aspect)
            self._refresh_safety_targets()
        return CommandResult(True, "set_signal", "signal updated")

    set_signal_aspect = set_signal

    def add_signal(
        self,
        signal_id: str,
        protects_block_id: str,
        *,
        aspect: str = "red",
    ) -> CommandResult:
        """Register a signal boundary with its initial aspect."""

        return self.set_signal(signal_id, aspect, protects_block_id=protects_block_id)

    @property
    def authorities(self) -> Mapping[str, tuple[str, ...]]:
        """Return explicit authority limits in deterministic order."""

        with self._lock:
            return dict(sorted(self._authorities.items()))

    @property
    def signals(self) -> Mapping[str, tuple[str, str]]:
        """Return signal ID to protected block/aspect mappings."""

        with self._lock:
            return {
                signal_id: (signal.protects_block_id, signal.aspect)
                for signal_id, signal in sorted(self._signals.items())
            }

    def braking_distance(self, speed: float) -> float:
        """Return the normalized distance needed to brake to zero."""

        self._validate_speed(speed)
        return (float(speed) ** 2) / (2.0 * self.acceleration)

    def set_turnout(self, turnout_id: str, position: int) -> CommandResult:
        """Store a deterministic turnout position (normally 0 or 1)."""

        if position not in (0, 1):
            return CommandResult(False, "set_turnout", "position must be 0 or 1")
        with self._lock:
            self._turnouts[str(turnout_id)] = int(position)
        return CommandResult(True, "set_turnout", "turnout updated")

    def tick(self, count: int = 1) -> TrackSnapshot:
        """Advance exactly ``count`` fixed-size ticks and return the result."""

        if count < 0:
            raise ValueError("count cannot be negative")
        with self._lock:
            for _ in range(count):
                self._advance_one_tick()
            return self._snapshot()

    def advance(self, count: int = 1) -> TrackSnapshot:
        """Alias for :meth:`tick` used by schedule simulations."""

        return self.tick(count)

    def get_snapshot(self) -> TrackSnapshot:
        """Return the current state without advancing time."""

        with self._lock:
            return self._snapshot()

    def _advance_one_tick(self) -> None:
        self._tick += 1
        if not self._powered:
            return
        occupied_by = {train.block_id: train.train_id for train in self._trains.values()}
        for train in self._trains.values():
            boundary = self._next_safety_boundary(train, occupied_by)
            train.target_speed = self._effective_target(train, boundary)
            train.speed = self._approach_speed(train.speed, train.target_speed)
            train.speed = min(train.speed, self._connection_limit(train))
            if train.speed <= 0:
                continue

            movement = train.speed * self.tick_seconds
            if boundary is not None and movement >= boundary.distance:
                self._hold_at_boundary(train)
                continue

            previous_block = train.block_id
            train.position += movement
            while train.position >= 1.0:
                next_index = train.route_index + train.direction
                if not (0 <= next_index < len(train.route)):
                    train.position = 1.0
                    train.speed = 0.0
                    train.target_speed = 0.0
                    break
                boundary = self._next_safety_boundary(train, occupied_by)
                if boundary is not None:
                    self._hold_at_boundary(train)
                    break
                train.position -= 1.0
                train.route_index = next_index
                train.block_id = train.route[train.route_index]
                # Any residual time in this tick must use the new zone's cap.
                new_speed = min(train.speed, self._connection_limit(train))
                if train.speed > 0:
                    train.position *= new_speed / train.speed
                train.speed = new_speed
                train.target_speed = self._effective_target(train, self._next_safety_boundary(train, occupied_by))
                if occupied_by.get(previous_block) == train.train_id:
                    del occupied_by[previous_block]
                occupied_by[train.block_id] = train.train_id
                previous_block = train.block_id

    def _refresh_safety_targets(self) -> None:
        """Apply current safety limits without advancing the fixed-step clock."""

        occupied_by = {train.block_id: train.train_id for train in self._trains.values()}
        for train in self._trains.values():
            boundary = self._next_safety_boundary(train, occupied_by)
            train.target_speed = self._effective_target(train, boundary)

    def _effective_target(self, train: _Train, boundary: _SafetyBoundary | None) -> float:
        if not self._powered:
            return 0.0
        requested = min(train.commanded_speed, self._connection_limit(train))
        if boundary is None:
            return requested
        projected_speed = self._approach_speed(train.speed, requested)
        if self.braking_distance(max(train.speed, projected_speed)) >= boundary.distance:
            return 0.0
        return requested

    def _next_safety_boundary(
        self,
        train: _Train,
        occupied_by: Mapping[str, str],
    ) -> _SafetyBoundary | None:
        next_index = train.route_index + train.direction
        if not (0 <= next_index < len(train.route)):
            # The end of a route is a real boundary, but preserve the legacy
            # terminal-block behavior by only enforcing it while in that last
            # block; a clear next block remains enterable as before.
            return _SafetyBoundary(1.0 - train.position, "route_end", train.block_id)

        next_block = train.route[next_index]
        other_train = occupied_by.get(next_block)
        if other_train is not None and other_train != train.train_id:
            return _SafetyBoundary(1.0 - train.position, "occupied_block", next_block)

        authority = self._authorities.get(train.train_id)
        if authority is not None and next_block not in authority:
            return _SafetyBoundary(1.0 - train.position, "blocked_authority", next_block)

        for signal in self._signals.values():
            if signal.protects_block_id == next_block and signal.aspect in self._RESTRICTIVE_SIGNAL_ASPECTS:
                return _SafetyBoundary(1.0 - train.position, "restrictive_signal", next_block)
        return None

    def _hold_at_boundary(self, train: _Train) -> None:
        train.position = min(train.position, 1.0 - self._BOUNDARY_EPSILON)
        train.speed = 0.0
        train.target_speed = 0.0

    def _approach_speed(self, speed: float, target_speed: float) -> float:
        delta = self.acceleration * self.tick_seconds
        if speed < target_speed:
            return min(target_speed, speed + delta)
        if speed > target_speed:
            return max(target_speed, speed - delta)
        return speed

    def _snapshot(self) -> TrackSnapshot:
        motions = tuple(
            TrainMotion(
                train_id=train.train_id,
                block_id=train.block_id,
                position=round(train.position, 12),
                speed=round(train.speed, 12),
                target_speed=round(train.target_speed, 12),
                direction=train.direction,
                route=train.route,
            )
            for train in sorted(self._trains.values(), key=lambda item: item.train_id)
        )
        occupied: dict[str, list[str]] = {}
        for motion in motions:
            occupied.setdefault(motion.block_id, []).append(motion.train_id)
        return TrackSnapshot(
            tick=self._tick,
            time_seconds=round(self._tick * self.tick_seconds, 12),
            powered=self._powered,
            trains=motions,
            occupied_blocks={key: tuple(value) for key, value in sorted(occupied.items())},
            turnouts=dict(sorted(self._turnouts.items())),
        )

    def _normalise_route(self, block_id: str, route: Sequence[str]) -> tuple[str, ...]:
        values = tuple(str(item) for item in route if str(item))
        if not values:
            values = (block_id,)
        elif block_id not in values:
            values = (block_id,) + values
        self._blocks.update(values)
        return values

    @staticmethod
    def _validate_speed(speed: float) -> None:
        if not 0.0 <= float(speed) <= 1.0:
            raise ValueError("speed must be between 0 and 1")
