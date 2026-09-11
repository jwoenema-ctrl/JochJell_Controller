"""Deterministic graph construction from a layout snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable

from .models import LayoutSnapshot, Point, TurnoutPosition


class GraphNodeKind(str, Enum):
    """Kinds of nodes that can participate in layout routing."""

    BLOCK = "block"
    WAYPOINT = "waypoint"
    TURNTABLE = "turntable"


@dataclass(frozen=True, slots=True)
class GraphNode:
    """A routable graph node."""

    id: str
    kind: GraphNodeKind
    position: Point | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("graph node ID must be a non-empty string")


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A directed, positive-cost graph edge."""

    source_id: str
    target_id: str
    cost: float = 1.0
    turnout_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise ValueError("graph edge endpoints must be non-empty")
        if self.source_id == self.target_id:
            raise ValueError("graph edges must connect distinct nodes")
        if not math.isfinite(float(self.cost)) or self.cost <= 0:
            raise ValueError("graph edge cost must be a positive finite number")
        object.__setattr__(self, "cost", float(self.cost))

    @property
    def key(self) -> tuple[str, str]:
        """Return the directed edge key used by route filters."""

        return (self.source_id, self.target_id)


class GraphBuildError(ValueError):
    """Raised when a snapshot references a graph node that does not exist."""


@dataclass(frozen=True, slots=True)
class LayoutGraph:
    """Immutable directed graph with deterministic neighbor ordering."""

    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        edges = tuple(self.edges)
        node_ids = tuple(node.id for node in nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("graph nodes must have unique IDs")
        node_set = set(node_ids)
        for edge in edges:
            if edge.source_id not in node_set or edge.target_id not in node_set:
                raise ValueError("graph edge references an unknown node")
        object.__setattr__(self, "nodes", tuple(sorted(nodes, key=lambda node: node.id)))
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(edges, key=lambda edge: (edge.source_id, edge.target_id, edge.cost, edge.turnout_id or ""))),
        )

    def node(self, node_id: str) -> GraphNode | None:
        """Return a node by ID, or ``None`` when it is absent."""

        return next((node for node in self.nodes if node.id == node_id), None)

    def require_node(self, node_id: str) -> GraphNode:
        """Return a node or raise ``GraphBuildError`` with a useful message."""

        node = self.node(node_id)
        if node is None:
            raise GraphBuildError(f"unknown graph node: {node_id}")
        return node

    def neighbors(
        self,
        node_id: str,
        *,
        blocked_nodes: Iterable[str] = (),
        blocked_edges: Iterable[tuple[str, str]] = (),
    ) -> tuple[GraphEdge, ...]:
        """Return usable outgoing edges in stable target order."""

        self.require_node(node_id)
        blocked_node_set = frozenset(blocked_nodes)
        blocked_edge_set = frozenset(blocked_edges)
        return tuple(
            edge
            for edge in self.edges
            if edge.source_id == node_id
            and edge.target_id not in blocked_node_set
            and edge.key not in blocked_edge_set
        )

    def estimate_cost(self, source_id: str, target_id: str) -> float:
        """Return Euclidean distance when both nodes have coordinates, else zero."""

        source = self.require_node(source_id)
        target = self.require_node(target_id)
        if source.position is None or target.position is None:
            return 0.0
        return math.hypot(source.position.x - target.position.x, source.position.y - target.position.y)


class LayoutGraphBuilder:
    """Build a routable graph from the topology in :class:`LayoutSnapshot`.

    Block neighbor links are always bidirectional.  A turnout contributes a
    bidirectional link only for its selected branch; an unknown turnout is
    therefore safely unroutable.  Waypoints and turntables are represented as
    explicit nodes, which lets later editors attach coordinates and metadata.
    """

    def build(self, snapshot: LayoutSnapshot) -> LayoutGraph:
        """Build and validate a deterministic graph from ``snapshot``."""

        if not isinstance(snapshot, LayoutSnapshot):
            raise TypeError("snapshot must be a LayoutSnapshot")
        nodes: dict[str, GraphNode] = {}
        edges: set[GraphEdge] = set()

        for block in snapshot.blocks:
            nodes[block.id] = GraphNode(block.id, GraphNodeKind.BLOCK, block.position)
        for waypoint in snapshot.waypoints:
            if waypoint.id in nodes:
                raise GraphBuildError(f"duplicate graph node ID: {waypoint.id}")
            nodes[waypoint.id] = GraphNode(waypoint.id, GraphNodeKind.WAYPOINT, waypoint.position)
        for turntable in snapshot.turntables:
            if turntable.id in nodes:
                raise GraphBuildError(f"duplicate graph node ID: {turntable.id}")
            nodes[turntable.id] = GraphNode(turntable.id, GraphNodeKind.TURNTABLE, turntable.position)

        def require_node(node_id: str, owner: str) -> None:
            if node_id not in nodes:
                raise GraphBuildError(f"{owner} references unknown graph node: {node_id}")

        def add_bidirectional(source_id: str, target_id: str, *, turnout_id: str | None = None) -> None:
            require_node(source_id, "edge")
            require_node(target_id, "edge")
            edges.add(GraphEdge(source_id, target_id, turnout_id=turnout_id))
            edges.add(GraphEdge(target_id, source_id, turnout_id=turnout_id))

        for block in snapshot.blocks:
            for neighbor_id in block.neighbor_ids:
                add_bidirectional(block.id, neighbor_id)

        for waypoint in snapshot.waypoints:
            for connected_id in waypoint.connected_node_ids:
                add_bidirectional(waypoint.id, connected_id)

        for turntable in snapshot.turntables:
            for block_id in turntable.connected_block_ids:
                add_bidirectional(turntable.id, block_id)

        for turnout in snapshot.turnouts:
            if turnout.position is TurnoutPosition.UNKNOWN:
                continue
            selected_id = (
                turnout.straight_block_id
                if turnout.position is TurnoutPosition.STRAIGHT
                else turnout.diverging_block_id
            )
            add_bidirectional(turnout.entry_block_id, selected_id, turnout_id=turnout.id)

        return LayoutGraph(tuple(nodes.values()), tuple(edges))
