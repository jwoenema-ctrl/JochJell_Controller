"""Directed, train-specific speed restrictions, independent of track hardware."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence
from backend.core.models import ConnectionSpeedLimit, TrackSection


def next_connection(block_id: str, route: Sequence[str], direction: int = 1) -> tuple[str, str] | None:
    """A zone starts at the source block and ends on entry to its successor."""
    if block_id not in route:
        return None
    index = route.index(block_id) + (1 if direction >= 0 else -1)
    return (block_id, route[index]) if 0 <= index < len(route) else None


class ConnectionSpeedPolicy:
    def __init__(self, rules: Iterable[ConnectionSpeedLimit] = (), maximums: Mapping[str, float] | None = None,
                 sections: Iterable[TrackSection] = ()):
        self.rules = {(r.from_block_id, r.to_block_id): r for r in rules}
        self.maximums = dict(maximums or {})
        self.section_limits: dict[tuple[str, str], float] = {}
        # Hardware reports blocks rather than exact positions. Enforce the
        # tightest section limit throughout the connection in either direction.
        for section in sections:
            if section.speed_limit_kmh is None:
                continue
            left, right = section.from_block_id, section.to_block_id
            for pair in ((left, right), (right, left)):
                self.section_limits[pair] = min(self.section_limits.get(pair, section.speed_limit_kmh), section.speed_limit_kmh)
                self.rules.setdefault(pair, ConnectionSpeedLimit(*pair))

    def limit_kmh(self, train_id: str, connection: tuple[str, str] | None) -> float | None:
        rule = self.rules.get(connection)
        connection_limit = dict(rule.train_speed_limits).get(train_id, rule.speed_limit_kmh) if rule else None
        section_limit = self.section_limits.get(connection)
        limits = [value for value in (connection_limit, section_limit) if value is not None]
        return min(limits) if limits else None

    def normalized_limit(self, train_id: str, connection: tuple[str, str] | None) -> float:
        limit = self.limit_kmh(train_id, connection)
        if limit is None:
            return 1.0
        maximum = self.maximums.get(train_id, 140.0)
        return min(1.0, limit / maximum) if maximum > 0 else 0.0
