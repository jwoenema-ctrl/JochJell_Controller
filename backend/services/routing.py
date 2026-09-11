"""Pure graph routing helpers for A* and breadth-first fallback planning."""

from __future__ import annotations

import heapq
from collections import deque
from itertools import count
from typing import Callable, Hashable, Iterable, Mapping, TypeVar


Node = TypeVar("Node", bound=Hashable)
NeighborProvider = Callable[[Node], Iterable[Node]]
CostProvider = Callable[[Node, Node], float]
Heuristic = Callable[[Node, Node], float]


def breadth_first_route(
    start: Node,
    goal: Node,
    neighbors: NeighborProvider[Node] | Mapping[Node, Iterable[Node]],
) -> tuple[Node, ...]:
    """Return the shortest unweighted route, or an empty tuple if unreachable."""

    if start == goal:
        return (start,)
    get_neighbors = _provider(neighbors)
    queue: deque[Node] = deque([start])
    parent: dict[Node, Node | None] = {start: None}
    while queue:
        current = queue.popleft()
        for neighbor in _ordered(get_neighbors(current)):
            if neighbor in parent:
                continue
            parent[neighbor] = current
            if neighbor == goal:
                return _reconstruct(parent, goal)
            queue.append(neighbor)
    return ()


def a_star_route(
    start: Node,
    goal: Node,
    neighbors: NeighborProvider[Node] | Mapping[Node, Iterable[Node]],
    *,
    cost: CostProvider[Node] | None = None,
    heuristic: Heuristic[Node] | None = None,
) -> tuple[Node, ...]:
    """Return a deterministic lowest-cost route, or an empty tuple."""

    if start == goal:
        return (start,)
    get_neighbors = _provider(neighbors)
    edge_cost = cost or (lambda _left, _right: 1.0)
    estimate = heuristic or (lambda _left, _right: 0.0)
    sequence = count()
    open_set: list[tuple[float, int, Node]] = [(float(estimate(start, goal)), next(sequence), start)]
    parent: dict[Node, Node | None] = {start: None}
    best_cost: dict[Node, float] = {start: 0.0}
    while open_set:
        _, _, current = heapq.heappop(open_set)
        if current == goal:
            return _reconstruct(parent, goal)
        for neighbor in _ordered(get_neighbors(current)):
            step = float(edge_cost(current, neighbor))
            if step < 0:
                raise ValueError("edge costs cannot be negative")
            candidate = best_cost[current] + step
            if candidate >= best_cost.get(neighbor, float("inf")):
                continue
            best_cost[neighbor] = candidate
            parent[neighbor] = current
            priority = candidate + float(estimate(neighbor, goal))
            heapq.heappush(open_set, (priority, next(sequence), neighbor))
    return ()


def _provider(
    neighbors: NeighborProvider[Node] | Mapping[Node, Iterable[Node]],
) -> NeighborProvider[Node]:
    return neighbors if callable(neighbors) else lambda node: neighbors.get(node, ())


def _ordered(values: Iterable[Node]) -> tuple[Node, ...]:
    return tuple(sorted(values, key=lambda value: (type(value).__name__, repr(value))))


def _reconstruct(parent: Mapping[Node, Node | None], goal: Node) -> tuple[Node, ...]:
    route: list[Node] = []
    current: Node | None = goal
    while current is not None:
        route.append(current)
        current = parent[current]
    route.reverse()
    return tuple(route)


# Short aliases keep integration code readable.
a_star = a_star_route
breadth_first_search = breadth_first_route

