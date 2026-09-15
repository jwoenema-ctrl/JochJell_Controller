"""Saved locomotive presence detection.

The service deliberately knows nothing about the transport used to query a
layout.  Callers inject a probe that accepts a DCC address and returns either
the detected state or a truthy/falsey value.  This keeps Z21 UDP details out
of the application service and makes the detector straightforward to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


Probe = Callable[[int], Any]


@dataclass(frozen=True)
class TrainPresenceResult:
    """Result for one saved locomotive."""

    train_id: str
    dcc_address: int | None
    status: str
    detected: bool = False
    error: str | None = None
    response: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "train_id": self.train_id,
            "dcc_address": self.dcc_address,
            "status": self.status,
            "detected": self.detected,
            "error": self.error,
            "response": self.response,
        }


@dataclass(frozen=True)
class TrainPresenceSummary:
    """Aggregate result for a complete saved-locomotive scan."""

    total: int
    detected: int
    unknown: int
    errors: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "detected": self.detected,
            "unknown": self.unknown,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class TrainPresenceScan:
    """Per-train results and the corresponding aggregate summary."""

    results: tuple[TrainPresenceResult, ...]
    summary: TrainPresenceSummary

    def as_dict(self) -> dict[str, Any]:
        return {
            "results": [result.as_dict() for result in self.results],
            "summary": self.summary.as_dict(),
        }


class SavedTrainPresenceService:
    """Ping every saved locomotive DCC address using an injected probe.

    ``saved_trains`` may be any iterable of mappings or objects.  The service
    looks for ``train_id`` (falling back to ``id``) and ``dcc_address`` (also
    accepting ``address``).  A missing/invalid address is reported as
    ``unknown``.  Probe exceptions are isolated to that train and reported as
    ``error`` so one failed query cannot abort the complete scan.

    The probe result is interpreted as follows:

    * ``None`` means the address could not be identified (``unknown``).
    * ``False`` means a response was received and the locomotive was not
      detected (``unknown``).
    * Mapping responses may explicitly expose ``detected``, ``present``,
      ``occupied``, or ``identified``; an explicit false value is unknown.
    * Any other value means the locomotive was detected (``detected``).

    A probe can return a richer response (for example a protocol response
    object or dictionary); that value is retained in ``response`` for the
    caller and serialized as-is by ``as_dict``.
    """

    def __init__(self, probe: Probe):
        if not callable(probe):
            raise TypeError("probe must be callable")
        self._probe = probe

    def scan(self, saved_trains: Iterable[Mapping[str, Any] | Any]) -> TrainPresenceScan:
        results: list[TrainPresenceResult] = []
        for index, train in enumerate(saved_trains):
            train_id = self._value(train, "train_id", self._value(train, "id", f"train-{index + 1}"))
            train_id = str(train_id)
            raw_address = self._value(train, "dcc_address", self._value(train, "address"))
            address = self._normalise_address(raw_address)

            if address is None:
                results.append(
                    TrainPresenceResult(
                        train_id=train_id,
                        dcc_address=None,
                        status="unknown",
                    )
                )
                continue

            try:
                response = self._probe(address)
            except Exception as exc:  # Probe failures are per-train results.
                results.append(
                    TrainPresenceResult(
                        train_id=train_id,
                        dcc_address=address,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            detected = self._is_detected(response)
            results.append(
                TrainPresenceResult(
                    train_id=train_id,
                    dcc_address=address,
                    status="detected" if detected else "unknown",
                    detected=detected,
                    response=response,
                )
            )

        summary = TrainPresenceSummary(
            total=len(results),
            detected=sum(result.status == "detected" for result in results),
            unknown=sum(result.status == "unknown" for result in results),
            errors=sum(result.status == "error" for result in results),
        )
        return TrainPresenceScan(results=tuple(results), summary=summary)

    @staticmethod
    def _value(train: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
        if isinstance(train, Mapping):
            return train.get(key, default)
        return getattr(train, key, default)

    @staticmethod
    def _normalise_address(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            address = int(value)
        except (TypeError, ValueError):
            return None
        return address if 1 <= address <= 9999 else None

    @staticmethod
    def _is_detected(response: Any) -> bool:
        if response is None or response is False:
            return False
        if isinstance(response, Mapping):
            for key in ("detected", "present", "occupied", "identified"):
                if key in response:
                    return bool(response[key])
        return True


# Short alias for integrations that prefer a concise service name.
TrainPresenceService = SavedTrainPresenceService
