"""Continuous route reservation updates for automatic dispatching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


RouteProvider = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class RouteUpdate:
    """Result of one train's route reservation attempt."""

    train_id: str
    route: tuple[str, ...]
    reserved: tuple[str, ...]
    blocked: bool = False
    blocked_block: str | None = None
    blocked_by: str | None = None


class ConstantRouteUpdater:
    """Re-apply desired routes every cycle with deterministic first-fit claims.

    Reservations are rebuilt in sorted train-ID order on each update.  A route
    is reserved only up to the first occupied or already-claimed block, so a
    dispatcher can stop a train before another train's protected section.
    """

    def __init__(self, route_provider: RouteProvider | None = None) -> None:
        self.route_provider = route_provider
        self._desired: dict[str, tuple[str, ...]] = {}
        self._reservations: dict[str, str] = {}
        self._last_updates: dict[str, RouteUpdate] = {}

    @property
    def reservations(self) -> Mapping[str, str]:
        """Return a read-only view-like copy of block ownership."""

        return dict(self._reservations)

    @property
    def desired_routes(self) -> Mapping[str, tuple[str, ...]]:
        """Return the currently configured desired routes."""

        return dict(self._desired)

    def set_route(self, train_id: str, route: Iterable[str]) -> None:
        """Set or replace a train's desired block route."""

        if not train_id:
            raise ValueError("train_id is required")
        values = tuple(dict.fromkeys(str(block) for block in route if str(block)))
        if not values:
            raise ValueError("route must contain at least one block")
        self._desired[train_id] = values

    def register_train(self, train_id: str, route: Iterable[str] | None = None) -> None:
        """Register a train, optionally with its initial desired route."""

        if route is not None:
            self.set_route(train_id, route)
        elif train_id not in self._desired:
            self._desired[train_id] = ()

    def release_train(self, train_id: str) -> None:
        """Release reservations and desired route for one train."""

        self._desired.pop(train_id, None)
        self._last_updates.pop(train_id, None)
        for block_id, owner in tuple(self._reservations.items()):
            if owner == train_id:
                del self._reservations[block_id]

    def update(
        self,
        occupied_blocks: Mapping[str, Iterable[str]] | None = None,
    ) -> tuple[RouteUpdate, ...]:
        """Rebuild reservations and return one result per registered train."""

        occupied = _normalise_occupancy(occupied_blocks or {})
        self._reservations.clear()
        updates: list[RouteUpdate] = []
        for train_id in sorted(self._desired):
            route = self._desired[train_id]
            if not route and self.route_provider is not None:
                route = tuple(dict.fromkeys(str(block) for block in self.route_provider(train_id) if str(block)))
                self._desired[train_id] = route
            reserved: list[str] = []
            blocked_block = None
            blocked_by = None
            for block_id in route:
                current_occupants = occupied.get(block_id, ())
                other_occupant = next((item for item in current_occupants if item != train_id), None)
                owner = self._reservations.get(block_id)
                if other_occupant is not None:
                    blocked_block, blocked_by = block_id, other_occupant
                    break
                if owner is not None and owner != train_id:
                    blocked_block, blocked_by = block_id, owner
                    break
                self._reservations[block_id] = train_id
                reserved.append(block_id)
            update = RouteUpdate(
                train_id=train_id,
                route=route,
                reserved=tuple(reserved),
                blocked=blocked_block is not None,
                blocked_block=blocked_block,
                blocked_by=blocked_by,
            )
            updates.append(update)
            self._last_updates[train_id] = update
        return tuple(updates)

    refresh = update

    def update_from_snapshot(self, snapshot: object) -> tuple[RouteUpdate, ...]:
        """Accept a core/adapter snapshot without coupling to its concrete type."""

        occupancy = getattr(snapshot, "occupied_blocks", {})
        return self.update(occupancy)


def _normalise_occupancy(occupied: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    normalised: dict[str, tuple[str, ...]] = {}
    for block_id, trains in occupied.items():
        if isinstance(trains, str):
            values = (trains,)
        else:
            values = tuple(str(train) for train in trains)
        normalised[str(block_id)] = values
    return normalised

