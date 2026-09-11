"""Explicit manual/automatic control-mode switching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .dispatcher import ControlMode, Dispatcher


@dataclass(frozen=True)
class ModeSwitchResult:
    """Result for one requested train mode change."""

    train_id: str
    mode: ControlMode
    accepted: bool


class AutomaticSystemSwitcher:
    """Centralize safe transitions between manual, automatic and stopped modes."""

    def __init__(self, dispatcher: Dispatcher) -> None:
        self.dispatcher = dispatcher

    def switch(self, train_id: str, mode: ControlMode | str) -> ModeSwitchResult:
        selected = ControlMode(mode)
        accepted = self.dispatcher.set_mode(train_id, selected)
        return ModeSwitchResult(train_id, selected, accepted)

    def switch_many(self, modes: Mapping[str, ControlMode | str]) -> tuple[ModeSwitchResult, ...]:
        return tuple(self.switch(train_id, mode) for train_id, mode in sorted(modes.items()))

    def stop_all(self, train_ids: Iterable[str] | None = None) -> tuple[str, ...]:
        if train_ids is None:
            return self.dispatcher.emergency_stop()
        stopped = []
        for train_id in sorted(train_ids):
            self.switch(train_id, ControlMode.STOPPED)
            stopped.append(train_id)
        return tuple(stopped)

