"""Directed, train-specific speed restrictions, independent of track hardware."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence
from backend.core.models import ConnectionSpeedLimit


def next_connection(block_id: str, route: Sequence[str], direction: int = 1) -> tuple[str, str] | None:
    """A zone starts at the source block and ends on entry to its successor."""
    if block_id not in route:
        return None
    index = route.index(block_id) + (1 if direction >= 0 else -1)
    return (block_id, route[index]) if 0 <= index < len(route) else None


class ConnectionSpeedPolicy:
    def __init__(self, rules: Iterable[ConnectionSpeedLimit] = (), maximums: Mapping[str, float] | None = None):
        self.rules = {(r.from_block_id, r.to_block_id): r for r in rules}
        self.maximums = dict(maximums or {})

    def limit_kmh(self, train_id: str, connection: tuple[str, str] | None) -> float | None:
        rule = self.rules.get(connection)
        if rule is None:
            return None
        return dict(rule.train_speed_limits).get(train_id, rule.speed_limit_kmh)

    def normalized_limit(self, train_id: str, connection: tuple[str, str] | None) -> float:
        limit = self.limit_kmh(train_id, connection)
        if limit is None:
            return 1.0
        maximum = self.maximums.get(train_id, 140.0)
        return min(1.0, limit / maximum) if maximum > 0 else 0.0
