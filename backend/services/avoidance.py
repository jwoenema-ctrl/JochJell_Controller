"""Occupancy and reservation conflict detection for safe dispatching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class AvoidanceConflict:
    """A physical or planned conflict that requires a stop or reroute."""

    block_id: str
    trains: tuple[str, ...]
    kind: str
    recommended_action: str = "stop"


class AvoidanceDetector:
    """Detect same-block occupancy and occupied reservation conflicts."""

    def detect(
        self,
        occupied_blocks: Mapping[str, Iterable[str]] | object,
        reservations: Mapping[str, str] | None = None,
    ) -> tuple[AvoidanceConflict, ...]:
        """Return stable conflicts from an occupancy map or track snapshot."""

        if not isinstance(occupied_blocks, Mapping):
            occupied_blocks = getattr(occupied_blocks, "occupied_blocks", {})
        occupancy = _normalise(occupied_blocks)
        conflicts: list[AvoidanceConflict] = []
        for block_id in sorted(occupancy):
            trains = occupancy[block_id]
            if len(trains) > 1:
                conflicts.append(
                    AvoidanceConflict(block_id, trains, "multiple_trains_in_block", "emergency_stop")
                )
        for block_id, owner in sorted((reservations or {}).items()):
            occupants = occupancy.get(block_id, ())
            other_trains = tuple(train for train in occupants if train != owner)
            if other_trains:
                conflicts.append(
                    AvoidanceConflict(
                        block_id,
                        tuple(dict.fromkeys((owner,) + other_trains)),
                        "reservation_occupied_by_other_train",
                        "stop_reserved_train",
                    )
                )
        return tuple(conflicts)

    check = detect

    def safe_to_enter(
        self,
        train_id: str,
        block_id: str,
        occupied_blocks: Mapping[str, Iterable[str]],
        reservations: Mapping[str, str] | None = None,
    ) -> bool:
        """Return whether a train may enter a block right now."""

        occupants = _normalise(occupied_blocks).get(block_id, ())
        if any(train != train_id for train in occupants):
            return False
        owner = (reservations or {}).get(block_id)
        return owner in (None, train_id)


def _normalise(occupied: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for block_id, trains in occupied.items():
        values = (trains,) if isinstance(trains, str) else tuple(str(train) for train in trains)
        result[str(block_id)] = tuple(dict.fromkeys(values))
    return result

