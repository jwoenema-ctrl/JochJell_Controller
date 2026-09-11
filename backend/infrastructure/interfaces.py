"""Small integration contracts shared by physical and simulated track adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol


class ConnectionState(str, Enum):
    """Connection state exposed to the UI and higher-level services."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class ConnectionStatus:
    """A side-effect-free description of an adapter's latest connection check."""

    state: ConnectionState
    endpoint: str = ""
    detail: str = ""
    checked_at: float | None = None

    @property
    def connected(self) -> bool:
        return self.state is ConnectionState.CONNECTED


@dataclass(frozen=True)
class CommandResult:
    """Result of a command accepted or rejected by a track adapter."""

    accepted: bool
    command: str
    detail: str = ""
    payload: bytes = b""


@dataclass(frozen=True)
class TrainMotion:
    """Immutable train motion state returned by a track adapter."""

    train_id: str
    block_id: str
    position: float
    speed: float
    target_speed: float
    direction: int = 1
    route: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackSnapshot:
    """Deterministic track state at one simulation or hardware observation tick."""

    tick: int
    time_seconds: float
    powered: bool
    trains: tuple[TrainMotion, ...] = ()
    occupied_blocks: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    turnouts: Mapping[str, int] = field(default_factory=dict)


class TrackSystem(Protocol):
    """Common surface consumed by dispatching services."""

    def get_snapshot(self) -> TrackSnapshot:
        """Return the latest immutable state."""

    def tick(self, count: int = 1) -> TrackSnapshot:
        """Advance or poll the system by a deterministic number of ticks."""

    def set_train_speed(self, train_id: str, speed: float) -> CommandResult:
        """Set a train's normalized target speed."""

    def stop_train(self, train_id: str) -> CommandResult:
        """Request a normal stop for one train."""


class ConnectionStatusProvider(Protocol):
    """Protocol implemented by adapters that can safely check connectivity."""

    def check_connection(self) -> ConnectionStatus:
        """Perform an explicit, bounded connection check."""

    def connection_status(self) -> ConnectionStatus:
        """Return the cached result of the last check."""


class TrainControlPort(Protocol):
    """Minimal train-control port used by the dispatcher."""

    def set_train_speed(self, train_id: str, speed: float) -> CommandResult:
        """Set a normalized target speed."""

    def stop_train(self, train_id: str) -> CommandResult:
        """Stop a train."""
