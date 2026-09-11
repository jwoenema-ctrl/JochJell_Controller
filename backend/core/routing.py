"""Deterministic breadth-first and A* route finding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import heapq
from typing import Callable, Iterable

from .graph import GraphNode, LayoutGraph


class RouteAlgorithm(str, Enum):
    """Algorithms supported by the core route finder."""

    BFS = "bfs"
    A_STAR = "a_star"


@dataclass(frozen=True, slots=True)
class Route:
    """A route represented by ordered node IDs and its accumulated cost."""

    node_ids: tuple[str, ...]
    cost: float
    algorithm: RouteAlgorithm

    @property
    def start_id(self) -> str:
        """Return the first node in the route."""

        return self.node_ids[0]

    @property
    def goal_id(self) -> str:
        """Return the last node in the route."""

        return self.node_ids[-1]


Heuristic = Callable[[GraphNode, GraphNode], float]


def _validate_request(
    graph: LayoutGraph,
    start_id: str,
    goal_id: str,
    blocked_nodes: Iterable[str],
) -> frozenset[str]:
    graph.require_node(start_id)
    graph.require_node(goal_id)
    blocked = frozenset(blocked_nodes)
    if start_id in blocked or goal_id in blocked:
        return blocked
    return blocked


def _reconstruct(parent: dict[str, str], start_id: str, goal_id: str) -> tuple[str, ...]:
    path = [goal_id]
    while path[-1] != start_id:
        path.append(parent[path[-1]])
    path.reverse()
    return tuple(path)


def breadth_first_search(
    graph: LayoutGraph,
    start_id: str,
    goal_id: str,
    *,
    blocked_nodes: Iterable[str] = (),
    blocked_edges: Iterable[tuple[str, str]] = (),
) -> Route | None:
    """Find a minimum-hop route with stable lexicographic tie breaking.

    BFS ignores edge costs when choosing a route, but the returned cost still
    contains the actual cost of the selected edges.
    """

    blocked = _validate_request(graph, start_id, goal_id, blocked_nodes)
    if start_id in blocked or goal_id in blocked:
        return None
    if start_id == goal_id:
        return Route((start_id,), 0.0, RouteAlgorithm.BFS)

    blocked_edge_set = frozenset(blocked_edges)
    queue: list[str] = [start_id]
    next_index = 0
    parent: dict[str, str] = {}
    cost_to: dict[str, float] = {start_id: 0.0}
    visited = {start_id}
    while next_index < len(queue):
        current = queue[next_index]
        next_index += 1
        for edge in graph.neighbors(current, blocked_nodes=blocked, blocked_edges=blocked_edge_set):
            if edge.target_id in visited:
                continue
            visited.add(edge.target_id)
            parent[edge.target_id] = current
            cost_to[edge.target_id] = cost_to[current] + edge.cost
            if edge.target_id == goal_id:
                path = _reconstruct(parent, start_id, goal_id)
                return Route(path, cost_to[goal_id], RouteAlgorithm.BFS)
            queue.append(edge.target_id)
    return None


def a_star(
    graph: LayoutGraph,
    start_id: str,
    goal_id: str,
    *,
    blocked_nodes: Iterable[str] = (),
    blocked_edges: Iterable[tuple[str, str]] = (),
    heuristic: Heuristic | None = None,
) -> Route | None:
    """Find a minimum-cost route using A* with deterministic tie breaking.

    The default heuristic is zero, which safely degrades to Dijkstra's
    algorithm for arbitrary layout edge costs.  A caller can supply a
    coordinate-based heuristic when its scale is known to be admissible.
    """

    blocked = _validate_request(graph, start_id, goal_id, blocked_nodes)
    if start_id in blocked or goal_id in blocked:
        return None
    if start_id == goal_id:
        return Route((start_id,), 0.0, RouteAlgorithm.A_STAR)

    blocked_edge_set = frozenset(blocked_edges)
    goal_node = graph.require_node(goal_id)
    heuristic_fn = heuristic or (lambda _source, _target: 0.0)
    start_node = graph.require_node(start_id)
    start_h = float(heuristic_fn(start_node, goal_node))
    if start_h < 0:
        raise ValueError("heuristic must not return a negative value")

    best_cost: dict[str, float] = {start_id: 0.0}
    best_path: dict[str, tuple[str, ...]] = {start_id: (start_id,)}
    heap: list[tuple[float, float, tuple[str, ...], str]] = [(start_h, 0.0, (start_id,), start_id)]

    while heap:
        _, current_cost, current_path, current_id = heapq.heappop(heap)
        if current_cost != best_cost.get(current_id) or current_path != best_path.get(current_id):
            continue
        if current_id == goal_id:
            return Route(current_path, current_cost, RouteAlgorithm.A_STAR)
        current_node = graph.require_node(current_id)
        for edge in graph.neighbors(current_id, blocked_nodes=blocked, blocked_edges=blocked_edge_set):
            candidate_cost = current_cost + edge.cost
            candidate_path = current_path + (edge.target_id,)
            previous_cost = best_cost.get(edge.target_id)
            previous_path = best_path.get(edge.target_id)
            if previous_cost is not None and (
                candidate_cost > previous_cost
                or (candidate_cost == previous_cost and previous_path is not None and candidate_path >= previous_path)
            ):
                continue
            target_node = graph.require_node(edge.target_id)
            candidate_h = float(heuristic_fn(target_node, goal_node))
            if candidate_h < 0:
                raise ValueError("heuristic must not return a negative value")
            best_cost[edge.target_id] = candidate_cost
            best_path[edge.target_id] = candidate_path
            heapq.heappush(
                heap,
                (candidate_cost + candidate_h, candidate_cost, candidate_path, edge.target_id),
            )
    return None


def find_route(
    graph: LayoutGraph,
    start_id: str,
    goal_id: str,
    *,
    algorithm: RouteAlgorithm = RouteAlgorithm.A_STAR,
    blocked_nodes: Iterable[str] = (),
    blocked_edges: Iterable[tuple[str, str]] = (),
    heuristic: Heuristic | None = None,
) -> Route | None:
    """Select BFS or A* by enum and return the resulting route."""

    if algorithm is RouteAlgorithm.BFS:
        return breadth_first_search(
            graph,
            start_id,
            goal_id,
            blocked_nodes=blocked_nodes,
            blocked_edges=blocked_edges,
        )
    if algorithm is RouteAlgorithm.A_STAR:
        return a_star(
            graph,
            start_id,
            goal_id,
            blocked_nodes=blocked_nodes,
            blocked_edges=blocked_edges,
            heuristic=heuristic,
        )
    raise ValueError(f"unsupported route algorithm: {algorithm}")
