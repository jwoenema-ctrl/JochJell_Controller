"""Deterministic movement authority and turnout interlocking.

The dispatcher owns train-control policy, while this service owns the small
piece of infrastructure safety that is independent of a simulator or Z21:
routes are checked against occupancy, reservations, topology, and turnout
locks before an automatic train receives movement authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from backend.core.graph import LayoutGraph


@dataclass(frozen=True, slots=True)
class MovementAuthority:
    """The safe prefix of one requested route and why it may be limited."""

    train_id: str
    requested_route: tuple[str, ...]
    safe_route: tuple[str, ...]
    blocked: bool = False
    reason: str = ""
    blocking_train: str | None = None
    locked_turnouts: tuple[str, ...] = ()


class MovementAuthorityService:
    """Calculate safe route prefixes and rebuild turnout locks every cycle.

    Rebuilding locks from the current route set makes a removed route release
    immediately. Sorted train IDs provide deterministic first-claim behavior
    when two automatic routes require the same turnout.
    """

    def __init__(self, graph: LayoutGraph | None = None) -> None:
        self.graph = graph
        self._locks: dict[str, str] = {}
        self._authorities: dict[str, MovementAuthority] = {}

    @property
    def locks(self) -> Mapping[str, str]:
        """Return turnout ID to owning train ID mappings."""

        return dict(self._locks)

    @property
    def authorities(self) -> Mapping[str, MovementAuthority]:
        """Return the most recent movement authorities."""

        return dict(self._authorities)

    def set_graph(self, graph: LayoutGraph | None) -> None:
        """Replace the topology used for edge and turnout validation."""

        if graph is not None and not isinstance(graph, LayoutGraph):
            raise TypeError("graph must be a LayoutGraph or None")
        self.graph = graph
        self._locks.clear()
        self._authorities.clear()

    def release_train(self, train_id: str) -> None:
        """Remove one train's cached authority and any turnout ownership."""

        selected = str(train_id)
        self._authorities.pop(selected, None)
        for turnout_id, owner in tuple(self._locks.items()):
            if owner == selected:
                del self._locks[turnout_id]

    def evaluate(
        self,
        routes: Mapping[str, Iterable[str]],
        occupied_blocks: Mapping[str, Iterable[str]] | None = None,
        reservations: Mapping[str, str] | None = None,
    ) -> Mapping[str, MovementAuthority]:
        """Evaluate routes and return one authority per train.

        The first block is assumed to be the train's current block. Every
        later block must be unoccupied by another train, unreserved by another
        train, connected in the graph, and free of a competing turnout lock.
        """

        occupied = _normalise_occupancy(occupied_blocks or {})
        claimed: dict[str, str] = {}
        authorities: dict[str, MovementAuthority] = {}
        for train_id in sorted(routes):
            selected_id = str(train_id)
            requested = _normalise_route(routes[train_id])
            if not requested:
                authorities[selected_id] = MovementAuthority(selected_id, requested, ())
                continue
            safe: list[str] = [requested[0]]
            locked: list[str] = []
            reason = ""
            blocker: str | None = None
            for next_block in requested[1:]:
                occupants = occupied.get(next_block, ())
                blocker = next((item for item in occupants if item != selected_id), None)
                if blocker is not None:
                    reason = "occupied_block"
                    break
                owner = (reservations or {}).get(next_block)
                if owner is not None and owner != selected_id:
                    blocker = str(owner)
                    reason = "reserved_block"
                    break
                edge = self._edge(safe[-1], next_block)
                if self.graph is not None and edge is None:
                    reason = "unknown_edge"
                    break
                turnout_id = edge.turnout_id if edge is not None else None
                if turnout_id:
                    current_owner = claimed.get(turnout_id)
                    if current_owner is not None and current_owner != selected_id:
                        blocker = current_owner
                        reason = "turnout_locked"
                        break
                    claimed[turnout_id] = selected_id
                    if turnout_id not in locked:
                        locked.append(turnout_id)
                safe.append(next_block)
            authorities[selected_id] = MovementAuthority(
                selected_id,
                requested,
                tuple(safe),
                blocked=bool(reason),
                reason=reason,
                blocking_train=blocker,
                locked_turnouts=tuple(locked),
            )
        self._locks = claimed
        self._authorities = authorities
        return dict(authorities)

    def _edge(self, source_id: str, target_id: str):
        if self.graph is None:
            return None
        matches = [edge for edge in self.graph.edges if edge.source_id == source_id and edge.target_id == target_id]
        if not matches:
            return None
        # Prefer a turnout edge when a topology link and a controlled branch
        # describe the same movement.
        return next((edge for edge in matches if edge.turnout_id), matches[0])


def _normalise_route(route: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in route if str(item).strip()))


def _normalise_occupancy(occupied: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for block_id, occupants in occupied.items():
        values = (occupants,) if isinstance(occupants, str) else tuple(str(item) for item in occupants)
        result[str(block_id)] = tuple(dict.fromkeys(values))
    return result
