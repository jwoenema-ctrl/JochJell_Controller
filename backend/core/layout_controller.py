"""Application-facing layout composition over the immutable core model."""

from __future__ import annotations

from collections.abc import Callable

from .events import EventController, LayoutChanged
from .graph import LayoutGraph, LayoutGraphBuilder
from .models import LayoutSnapshot
from .state import StateController, VersionedSnapshot


class LayoutController:
    """Own the current layout, its versioned state, events and route graph."""

    def __init__(
        self,
        snapshot: LayoutSnapshot | None = None,
        *,
        state_controller: StateController | None = None,
        event_controller: EventController | None = None,
        graph_builder: LayoutGraphBuilder | None = None,
    ) -> None:
        self.state_controller = state_controller or StateController(snapshot)
        self.event_controller = event_controller or EventController()
        self.graph_builder = graph_builder or LayoutGraphBuilder()

    def snapshot(self) -> VersionedSnapshot:
        """Return the current immutable layout and revision."""

        return self.state_controller.snapshot()

    def graph(self) -> LayoutGraph:
        """Build a deterministic routing graph from the current layout."""

        return self.graph_builder.build(self.snapshot().snapshot)

    def replace(self, snapshot: LayoutSnapshot) -> VersionedSnapshot:
        """Replace the layout and publish a typed change event."""

        committed = self.state_controller.replace(snapshot)
        self.event_controller.publish(LayoutChanged(revision=committed.version))
        return committed

    def update(self, updater: Callable[[LayoutSnapshot], LayoutSnapshot]) -> VersionedSnapshot:
        """Apply an immutable layout update and publish a typed change event."""

        committed = self.state_controller.update(updater)
        self.event_controller.publish(LayoutChanged(revision=committed.version))
        return committed

