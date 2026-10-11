"""Durable timetable and automation-plan storage."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping


class OperatingPlanRepository:
    """Store schedules and authored routines in a human-readable sidecar file."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path not in (None, "", ":memory:") else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any] | None:
        """Load the sidecar plan, returning ``None`` when it does not exist."""

        if self.path is None or not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        schedules = payload.get("schedules", [])
        routines = payload.get("routines", [])
        triggers = payload.get("track_triggers", [])
        block_feedback = payload.get("block_feedback", [])
        if not all(isinstance(value, list) for value in (schedules, routines, triggers, block_feedback)):
            return None
        return {
            "schedules": [deepcopy(item) for item in schedules if isinstance(item, dict)],
            "routines": [deepcopy(item) for item in routines if isinstance(item, dict)],
            "track_triggers": [deepcopy(item) for item in triggers if isinstance(item, dict)],
            "block_feedback": [deepcopy(item) for item in block_feedback if isinstance(item, dict)],
            "computer_feedback": deepcopy(payload.get("computer_feedback", {})),
            "computer_turnouts": deepcopy(payload.get("computer_turnouts", [])),
        }

    def save(self, schedules: list[Mapping[str, Any]], routines: list[Mapping[str, Any]], track_triggers=(), block_feedback=(), computer_feedback=None, computer_turnouts=()) -> None:
        """Atomically save the current timetable and routine definitions."""

        if self.path is None:
            return
        payload = {
            "version": 5,
            "schedules": deepcopy([dict(item) for item in schedules]),
            "routines": deepcopy([dict(item) for item in routines]),
            "track_triggers": deepcopy([dict(item) for item in track_triggers]),
            "block_feedback": deepcopy([dict(item) for item in block_feedback]),
            "computer_feedback": deepcopy(computer_feedback or {}),
            "computer_turnouts": deepcopy(list(computer_turnouts)),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)
