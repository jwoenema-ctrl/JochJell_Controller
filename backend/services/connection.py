"""Connection status polling that remains independent of hardware details."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.infrastructure.interfaces import ConnectionState, ConnectionStatus, ConnectionStatusProvider


@dataclass(frozen=True)
class ConnectionCheck:
    """One status sample and whether it differs from the previous sample."""

    status: ConnectionStatus
    changed: bool


class ConnectionChecker:
    """Poll an adapter on demand and retain the latest status transition."""

    def __init__(
        self,
        provider: ConnectionStatusProvider,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.provider = provider
        self.clock = clock
        self._last: ConnectionStatus | None = None

    @property
    def status(self) -> ConnectionStatus:
        """Return cached status, or disconnected before the first check."""

        if self._last is not None:
            return self._last
        return ConnectionStatus(ConnectionState.DISCONNECTED, detail="not checked")

    def check(self) -> ConnectionCheck:
        """Perform one adapter-defined bounded check."""

        current = self.provider.check_connection()
        changed = current != self._last
        self._last = current
        return ConnectionCheck(current, changed)

    poll = check

