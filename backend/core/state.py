"""Versioned in-memory state management for the core domain."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import Callable

from .models import LayoutSnapshot


@dataclass(frozen=True, slots=True)
class VersionedSnapshot:
    """A layout snapshot paired with the monotonically increasing state version."""

    version: int
    snapshot: LayoutSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or self.version < 0:
            raise ValueError("version must be a non-negative integer")
        if not isinstance(self.snapshot, LayoutSnapshot):
            raise TypeError("snapshot must be a LayoutSnapshot")
        if self.snapshot.revision != self.version:
            raise ValueError("snapshot revision must match version")


class StateVersionConflict(RuntimeError):
    """Raised when a compare-and-update sees a stale expected version."""


StateListener = Callable[[VersionedSnapshot], None]


class StateSubscription:
    """A removable subscription returned by :meth:`StateController.subscribe`."""

    def __init__(self, controller: "StateController", token: int) -> None:
        self._controller = controller
        self._token = token
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether this subscription has already been removed."""

        return self._closed

    def close(self) -> None:
        """Remove the listener; calling this method more than once is safe."""

        if not self._closed:
            self._controller._unsubscribe(self._token)
            self._closed = True

    def __enter__(self) -> "StateSubscription":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class StateController:
    """Thread-safe versioned state store with deterministic subscriptions.

    An updater receives the current immutable snapshot and returns a new one.
    The controller assigns the next revision and then invokes listeners in the
    order in which they subscribed.  Listener failures are allowed to surface
    after the state has been committed.
    """

    def __init__(self, initial: LayoutSnapshot | None = None) -> None:
        initial_snapshot = initial or LayoutSnapshot.empty()
        self._lock = RLock()
        self._current = VersionedSnapshot(initial_snapshot.revision, initial_snapshot)
        self._next_token = 1
        self._listeners: dict[int, StateListener] = {}

    @property
    def version(self) -> int:
        """Return the current state version."""

        with self._lock:
            return self._current.version

    def snapshot(self) -> VersionedSnapshot:
        """Return the latest snapshot and its version."""

        with self._lock:
            return self._current

    def subscribe(self, listener: StateListener, *, replay: bool = False) -> StateSubscription:
        """Subscribe to committed snapshots.

        When ``replay`` is true, the current snapshot is delivered immediately
        after registration.  Subscriptions are invoked in registration order.
        """

        if not callable(listener):
            raise TypeError("listener must be callable")
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._listeners[token] = listener
            current = self._current if replay else None
        subscription = StateSubscription(self, token)
        if current is not None:
            listener(current)
        return subscription

    def _unsubscribe(self, token: int) -> None:
        with self._lock:
            self._listeners.pop(token, None)

    def update(self, updater: Callable[[LayoutSnapshot], LayoutSnapshot]) -> VersionedSnapshot:
        """Apply an updater, commit a new version, and notify subscribers."""

        if not callable(updater):
            raise TypeError("updater must be callable")
        with self._lock:
            updated = updater(self._current.snapshot)
            if not isinstance(updated, LayoutSnapshot):
                raise TypeError("updater must return a LayoutSnapshot")
            next_version = self._current.version + 1
            committed = VersionedSnapshot(next_version, replace(updated, revision=next_version))
            self._current = committed
            listeners = tuple(self._listeners.values())
        self._notify(listeners, committed)
        return committed

    def replace(self, snapshot: LayoutSnapshot) -> VersionedSnapshot:
        """Commit a supplied snapshot as the next version."""

        if not isinstance(snapshot, LayoutSnapshot):
            raise TypeError("snapshot must be a LayoutSnapshot")
        return self.update(lambda _: snapshot)

    def compare_and_update(
        self,
        expected_version: int,
        updater: Callable[[LayoutSnapshot], LayoutSnapshot],
    ) -> VersionedSnapshot:
        """Update only when the caller still owns ``expected_version``."""

        with self._lock:
            if self._current.version != expected_version:
                raise StateVersionConflict(
                    f"expected version {expected_version}, current version is {self._current.version}"
                )
            updated = updater(self._current.snapshot)
            if not isinstance(updated, LayoutSnapshot):
                raise TypeError("updater must return a LayoutSnapshot")
            next_version = self._current.version + 1
            committed = VersionedSnapshot(next_version, replace(updated, revision=next_version))
            self._current = committed
            listeners = tuple(self._listeners.values())
        self._notify(listeners, committed)
        return committed

    @staticmethod
    def _notify(listeners: tuple[StateListener, ...], committed: VersionedSnapshot) -> None:
        first_error: Exception | None = None
        for listener in listeners:
            try:
                listener(committed)
            except Exception as error:  # Keep later listeners deterministic even if one fails.
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
