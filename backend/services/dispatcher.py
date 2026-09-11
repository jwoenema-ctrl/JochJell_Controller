"""Manual/automatic train-control arbitration and dispatch cycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .avoidance import AvoidanceConflict, AvoidanceDetector
from .interlocking import MovementAuthority, MovementAuthorityService


class ControlMode(str, Enum):
    """The source allowed to command a train."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"
    STOPPED = "stopped"


@dataclass
class TrainControlState:
    """Mutable dispatch state for one train."""

    train_id: str
    mode: ControlMode = ControlMode.MANUAL
    manual_speed: float = 0.0
    automatic_speed: float = 0.0
    last_command: str = ""

    @property
    def desired_speed(self) -> float:
        """Return the speed permitted by the current mode."""

        if self.mode is ControlMode.MANUAL:
            return self.manual_speed
        if self.mode is ControlMode.AUTOMATIC:
            return self.automatic_speed
        return 0.0


@dataclass(frozen=True)
class DispatchCycle:
    """Outcome of one dispatcher coordination cycle."""

    snapshot: object
    conflicts: tuple[AvoidanceConflict, ...]
    stopped_trains: tuple[str, ...]
    applied_trains: tuple[str, ...]


class Dispatcher:
    """Coordinate manual commands, automatic targets, routes, and safety.

    The track object is intentionally protocol-shaped: it only needs
    ``get_snapshot``, ``set_train_speed``, and ``stop_train``.  This keeps the
    service usable with the simulator, a future core state controller, or a
    physical adapter.
    """

    def __init__(
        self,
        track_system: Any,
        *,
        avoidance_detector: AvoidanceDetector | None = None,
        route_updater: Any | None = None,
        interlocking: MovementAuthorityService | None = None,
    ) -> None:
        self.track_system = track_system
        self.avoidance_detector = avoidance_detector or AvoidanceDetector()
        self.route_updater = route_updater
        self.interlocking = interlocking
        self._authorities: dict[str, MovementAuthority] = {}
        self._trains: dict[str, TrainControlState] = {}

    @property
    def trains(self) -> Mapping[str, TrainControlState]:
        """Return a copy of the registered control states."""

        return dict(self._trains)

    @property
    def authorities(self) -> Mapping[str, MovementAuthority]:
        """Return the latest movement authorities used by automatic dispatch."""

        return dict(self._authorities)

    def set_graph(self, graph: object | None) -> None:
        """Give the optional interlocking service the current layout graph."""

        if self.interlocking is not None:
            self.interlocking.set_graph(graph)  # type: ignore[arg-type]

    def register_train(
        self,
        train_id: str,
        *,
        mode: ControlMode | None = None,
    ) -> TrainControlState:
        """Register or return a train control state."""

        if not train_id:
            raise ValueError("train_id is required")
        state = self._trains.get(train_id)
        if state is None:
            state = TrainControlState(train_id, mode=ControlMode(mode or ControlMode.MANUAL))
            self._trains[train_id] = state
        elif mode is not None:
            state.mode = ControlMode(mode)
        return state

    def unregister_train(self, train_id: str) -> bool:
        """Stop tracking a train; route ownership is released if supported."""

        removed = self._trains.pop(train_id, None) is not None
        if self.route_updater is not None and hasattr(self.route_updater, "release_train"):
            self.route_updater.release_train(train_id)
        if self.interlocking is not None:
            self.interlocking.release_train(train_id)
        return removed

    def set_mode(self, train_id: str, mode: ControlMode) -> bool:
        """Switch control source without changing the stored targets."""

        state = self.register_train(train_id)
        state.mode = ControlMode(mode)
        if state.mode is ControlMode.STOPPED:
            self.track_system.stop_train(train_id)
        return True

    switch_control = set_mode

    def manual_speed(self, train_id: str, speed: float) -> Any:
        """Apply a manual speed only when the train is in manual mode."""

        _validate_speed(speed)
        state = self.register_train(train_id)
        if state.mode is not ControlMode.MANUAL:
            return _rejected("manual_speed", "train is not in manual mode")
        state.manual_speed = float(speed)
        state.last_command = "manual_speed"
        return self.track_system.set_train_speed(train_id, state.manual_speed)

    def automatic_speed(self, train_id: str, speed: float) -> Any:
        """Store an automatic target; it is applied during :meth:`tick`."""

        _validate_speed(speed)
        state = self.register_train(train_id)
        state.automatic_speed = float(speed)
        state.last_command = "automatic_speed"
        if state.mode is not ControlMode.AUTOMATIC:
            return _rejected("automatic_speed", "train is not in automatic mode")
        return self.track_system.set_train_speed(train_id, state.automatic_speed)

    def emergency_stop(self) -> tuple[str, ...]:
        """Stop every registered train and put it in STOPPED mode."""

        stopped: list[str] = []
        for train_id, state in sorted(self._trains.items()):
            self.track_system.stop_train(train_id)
            state.mode = ControlMode.STOPPED
            state.last_command = "emergency_stop"
            stopped.append(train_id)
        return tuple(stopped)

    def tick(self) -> DispatchCycle:
        """Run route/safety checks and apply safe automatic targets."""

        snapshot = self.track_system.get_snapshot()
        occupancy = getattr(snapshot, "occupied_blocks", {})
        reservations: Mapping[str, str] = {}
        updates = ()
        if self.route_updater is not None:
            updates = self.route_updater.update(occupancy)
            reservations = getattr(self.route_updater, "reservations", {})
        conflicts = self.avoidance_detector.detect(occupancy, reservations)
        if self.interlocking is not None and self.route_updater is not None:
            self._authorities = dict(
                self.interlocking.evaluate(
                    self.route_updater.desired_routes,
                    occupancy,
                    reservations,
                )
            )
        else:
            self._authorities = {}
        conflict_trains = {
            train
            for conflict in conflicts
            for train in conflict.trains
        }
        stopped: list[str] = []
        for train_id in sorted(conflict_trains):
            if train_id in self._trains:
                self.track_system.stop_train(train_id)
                self._trains[train_id].last_command = "avoidance_stop"
                stopped.append(train_id)

        applied: list[str] = []
        blocked_by_route = {
            update.train_id
            for update in updates
            if getattr(update, "blocked", False)
        }
        updates_by_train = {update.train_id: update for update in updates}
        for train_id, state in sorted(self._trains.items()):
            if state.mode is not ControlMode.AUTOMATIC:
                continue
            if train_id in conflict_trains:
                self.track_system.stop_train(train_id)
                if train_id not in stopped:
                    stopped.append(train_id)
                continue
            authority = self._authorities.get(train_id)
            if authority is not None and authority.blocked:
                if len(authority.safe_route) > 1 and hasattr(self.track_system, "set_train_route"):
                    self.track_system.set_train_route(train_id, authority.safe_route)
                    self.track_system.set_train_speed(train_id, state.automatic_speed)
                    applied.append(train_id)
                else:
                    self.track_system.stop_train(train_id)
                    if train_id not in stopped:
                        stopped.append(train_id)
                continue
            if train_id in blocked_by_route:
                update = updates_by_train.get(train_id)
                safe_prefix = tuple(getattr(update, "reserved", ())) if update is not None else ()
                if len(safe_prefix) > 1 and hasattr(self.track_system, "set_train_route"):
                    # A later occupied block protects the train, but should
                    # not prevent it reaching the end of the safe prefix.
                    self.track_system.set_train_route(train_id, safe_prefix)
                    self.track_system.set_train_speed(train_id, state.automatic_speed)
                    applied.append(train_id)
                else:
                    self.track_system.stop_train(train_id)
                    if train_id not in stopped:
                        stopped.append(train_id)
                continue
            update = updates_by_train.get(train_id)
            if update is not None and getattr(update, "route", ()) and hasattr(self.track_system, "set_train_route"):
                self.track_system.set_train_route(train_id, update.route)
            self.track_system.set_train_speed(train_id, state.automatic_speed)
            applied.append(train_id)
        return DispatchCycle(snapshot, conflicts, tuple(sorted(stopped)), tuple(applied))


ManualAutomaticCoordinator = Dispatcher


def _validate_speed(speed: float) -> None:
    if not 0.0 <= float(speed) <= 1.0:
        raise ValueError("speed must be between 0 and 1")


def _rejected(command: str, detail: str) -> object:
    """Use the common result type when available without coupling to an adapter."""

    try:
        from backend.infrastructure.interfaces import CommandResult

        return CommandResult(False, command, detail)
    except ImportError:
        return False
