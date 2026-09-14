"""Track-system adapter that translates normalized commands to Z21 LAN packets."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable, Mapping

from .interfaces import CommandResult, ConnectionStatus, TrackSnapshot, TrainMotion
from backend.services.connection_speed import ConnectionSpeedPolicy, next_connection
from .z21_telemetry import decode_system_state
from .z21 import encode_dataset
from .z21 import Z21LanTransport, build_rbus_get_data, build_set_loco_drive, build_set_track_power, build_set_turnout, decode_rbus_feedback


@dataclass
class Z21TrackSystem:
    """Minimal real-track implementation behind the same port as the simulator."""

    transport: Z21LanTransport

    def __init__(
        self,
        transport: Z21LanTransport,
        *,
        tick_seconds: float = 0.1,
        train_addresses: dict[str, int] | None = None,
        feedback_map: Mapping[tuple[int, int], str] | None = None,
    ) -> None:
        self.transport = transport
        self.tick_seconds = tick_seconds
        self._train_addresses = dict(train_addresses or {})
        self._feedback_map = dict(feedback_map or {})
        self._train_directions: dict[str, bool] = {train_id: True for train_id in self._train_addresses}
        self._snapshot = TrackSnapshot(0, 0.0, False)
        self._feedback_healthy = not bool(self._feedback_map)
        self._feedback_error = ""
        self._speed_policy = ConnectionSpeedPolicy()
        self._requested_speeds: dict[str, float] = {}
        self._effective_speeds: dict[str, float] = {}
        self._train_functions: dict[str, dict[int, bool]] = {}

    def configure_speed_limits(self, policy: ConnectionSpeedPolicy) -> None:
        self._speed_policy = policy
        for train_id, requested in tuple(self._requested_speeds.items()):
            if requested and self._limited_speed(train_id, requested) != self._effective_speeds.get(train_id, 0.0):
                result = self.set_train_speed(train_id, requested)
                if not result.accepted:
                    raise ValueError(result.detail or "connection speed limit command failed")

    def get_effective_speed(self, train_id: str) -> float:
        """Last accepted command, not a measured physical velocity."""
        return self._effective_speeds.get(train_id, 0.0)

    def get_train_speed_limit(self, train_id: str) -> float | None:
        motion = next((m for m in self._snapshot.trains if m.train_id == train_id), None)
        if motion and motion.block_id in motion.route:
            return self._speed_policy.limit_kmh(train_id, next_connection(motion.block_id, motion.route, motion.direction))
        limits = [value for edge in self._speed_policy.rules
                  if (value := self._speed_policy.limit_kmh(train_id, edge)) is not None]
        return min(limits) if limits else None

    def _limited_speed(self, train_id: str, speed: float) -> float:
        motion = next((m for m in self._snapshot.trains if m.train_id == train_id), None)
        if motion is not None:
            connection = next_connection(motion.block_id, motion.route, motion.direction)
            if connection is not None or motion.block_id in motion.route:
                return min(speed, self._speed_policy.normalized_limit(train_id, connection))
        # Without a reported traversal, never assume that a restricted zone
        # has been cleared. Use the most restrictive applicable configured cap.
        return min([speed] + [self._speed_policy.normalized_limit(train_id, edge)
                              for edge in self._speed_policy.rules])

    def report_train_position(self, train_id: str, block_id: str, route: tuple[str, ...]) -> CommandResult:
        old = next((m for m in self._snapshot.trains if m.train_id == train_id), None)
        motion = TrainMotion(train_id, block_id, 0.0, old.speed if old else self.get_effective_speed(train_id),
                             old.target_speed if old else self.get_effective_speed(train_id),
                             1 if self.get_train_direction(train_id) else -1, route)
        self._snapshot = replace(self._snapshot, trains=tuple(m for m in self._snapshot.trains if m.train_id != train_id) + (motion,))
        requested = self._requested_speeds.get(train_id, 0.0)
        if requested and self._limited_speed(train_id, requested) != motion.target_speed:
            return self.set_train_speed(train_id, requested)
        return CommandResult(True, "report_train_position", "position reported, not measured")

    def set_train_route(self, train_id: str, route: Iterable[str]) -> CommandResult:
        motion = next((m for m in self._snapshot.trains if m.train_id == train_id), None)
        if motion is None:
            return CommandResult(True, "set_train_route", "awaiting identified train position")
        return self.report_train_position(train_id, motion.block_id, tuple(route))

    def _record_speed(self, train_id: str, speed: float) -> None:
        self._effective_speeds[train_id] = speed
        self._snapshot = replace(self._snapshot, trains=tuple(
            replace(m, speed=speed, target_speed=speed) if m.train_id == train_id else m
            for m in self._snapshot.trains))

    def register_train(self, train_id: str, address: int, *, forward: bool = True) -> None:
        """Bind an application train ID to a validated DCC address."""

        if not train_id:
            raise ValueError("train_id is required")
        if not 1 <= int(address) <= 0x3FFF:
            raise ValueError("address must be between 1 and 16383")
        self._train_addresses[train_id] = int(address)
        self._train_directions[train_id] = bool(forward)

    bind_train = register_train

    def unregister_train(self, train_id: str) -> bool:
        """Remove a train/address binding without sending a hardware command."""

        removed = self._train_addresses.pop(train_id, None) is not None
        self._train_directions.pop(train_id, None)
        self._requested_speeds.pop(train_id, None)
        self._effective_speeds.pop(train_id, None)
        self._train_functions.pop(train_id, None)
        self._snapshot = replace(self._snapshot, trains=tuple(m for m in self._snapshot.trains if m.train_id != train_id))
        return removed

    def check_connection(self) -> ConnectionStatus:
        status = self.transport.check_connection()
        self._snapshot = replace(self._snapshot, powered=self._snapshot.powered and status.connected)
        return status

    def connection_status(self) -> ConnectionStatus:
        return self.transport.connection_status()

    def read_power_telemetry(self) -> dict:
        result, datasets = self.transport.request_datasets(
            encode_dataset(0x0085), expected_header=0x0084, command="system_state")
        if result.accepted:
            for dataset in datasets:
                if dataset.header == 0x0084:
                    try:
                        return decode_system_state(dataset.data)
                    except ValueError:
                        break
        return {"available": False, "reason": "No fresh Z21 power readings"}

    def rename_block(self, old: str, new: str) -> None:
        """Update feedback bindings without sending hardware commands."""
        self._feedback_map = {key: new if value == old else value for key, value in self._feedback_map.items()}
        self._snapshot = replace(self._snapshot,
            trains=tuple(replace(train, block_id=new if train.block_id == old else train.block_id,
                                 route=tuple(new if item == old else item for item in train.route))
                         for train in self._snapshot.trains),
            occupied_blocks={new if key == old else key: value for key, value in self._snapshot.occupied_blocks.items()})

    def get_snapshot(self) -> TrackSnapshot:
        return self._snapshot

    def tick(self, count: int = 1) -> TrackSnapshot:
        if count < 0:
            raise ValueError("count cannot be negative")
        self._snapshot = TrackSnapshot(self._snapshot.tick + count, self._snapshot.time_seconds + count * self.tick_seconds, self._snapshot.powered, self._snapshot.trains, self._snapshot.occupied_blocks, self._snapshot.turnouts)
        return self._snapshot

    def set_train_speed(self, train_id: str, speed: float) -> CommandResult:
        if not 0.0 <= float(speed) <= 1.0:
            raise ValueError("speed must be between 0 and 1")
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "set_train_speed", f"no DCC address registered for {train_id}")
        effective = self._limited_speed(train_id, speed)
        result = self.set_train_speed_by_address(
            address,
            effective,
            forward=self._train_directions.get(train_id, True),
            speed_limit=self._limited_speed(train_id, 1.0) if self.get_train_speed_limit(train_id) is not None else None,
        )
        if result.accepted:
            self._requested_speeds[train_id] = speed
            self._record_speed(train_id, effective)
        else:
            self._requested_speeds[train_id] = 0.0
        return result

    def set_train_speed_by_address(self, address: int, speed: float, *, forward: bool = True, speed_limit: float | None = None) -> CommandResult:
        if not 0.0 <= float(speed) <= 1.0:
            raise ValueError("speed must be between 0 and 1")
        dcc_speed = round(float(speed) * 126)
        if speed_limit is not None:
            dcc_speed = min(dcc_speed, math.floor(speed_limit * 126))
        # In 128-step DCC, value 1 is reserved for emergency stop. Keep a
        # small but non-zero normalized command a normal drive command.
        if dcc_speed == 1:
            dcc_speed = 0 if speed_limit is not None and speed_limit * 126 < 2 else 2
        try:
            packet = build_set_loco_drive(address, dcc_speed, forward=forward)
        except ValueError as exc:
            return CommandResult(False, "set_train_speed", str(exc))
        return self.transport.send_dataset(packet, command="set_loco_drive")

    def get_train_direction(self, train_id: str) -> bool:
        return self._train_directions.get(train_id, True)

    def set_train_direction(self, train_id: str, *, forward: bool) -> CommandResult:
        """Send a zero-speed direction packet; caller must require a stopped train."""
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "set_direction", "no DCC address registered")
        motion = next((m for m in self._snapshot.trains if m.train_id == train_id), None)
        if self._requested_speeds.get(train_id, 0) > 0 or self.get_effective_speed(train_id) > 0 or (motion and motion.target_speed > 0):
            return CommandResult(False, "set_direction", "stop the train before changing direction")
        result = self.stop_by_address(address, forward=forward)
        if result.accepted:
            self._train_directions[train_id] = forward
            self._snapshot = replace(self._snapshot, trains=tuple(
                replace(m, direction=1 if forward else -1) if m.train_id == train_id else m
                for m in self._snapshot.trains))
        return result

    def stop_train(self, train_id: str) -> CommandResult:
        self._requested_speeds[train_id] = 0.0
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "stop_train", f"no DCC address registered for {train_id}")
        result = self.stop_by_address(address, forward=self._train_directions.get(train_id, True))
        if result.accepted:
            self._record_speed(train_id, 0.0)
        return result

    def stop_by_address(self, address: int, *, forward: bool = True) -> CommandResult:
        packet = build_set_loco_drive(address, 0, forward=forward)
        return self.transport.send_dataset(packet, command="stop_train")

    def set_train_function(self, train_id: str, function_number: int, *, enabled: bool) -> CommandResult:
        """Switch one decoder function for a registered physical train."""

        try:
            function_number = int(function_number)
        except (TypeError, ValueError):
            return CommandResult(False, "set_loco_function", "function number must be an integer")
        if not 0 <= function_number <= 31:
            return CommandResult(False, "set_loco_function", "function number must be between 0 and 31")
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "set_loco_function", f"no DCC address registered for {train_id}")
        result = self.transport.set_loco_function(address, function_number, enabled=bool(enabled))
        if result.accepted:
            self._train_functions.setdefault(train_id, {})[function_number] = bool(enabled)
        return result

    def get_train_functions(self, train_id: str) -> Mapping[int, bool]:
        """Return the last function states acknowledged by the adapter."""

        return dict(self._train_functions.get(train_id, {}))

    def set_power(self, enabled: bool) -> CommandResult:
        """Switch Z21 track voltage using the LAN X-BUS command."""

        result = self.transport.send_dataset(build_set_track_power(bool(enabled)), command="set_power")
        if result.accepted:
            if not enabled:
                self._requested_speeds.clear()
                for train_id in tuple(self._effective_speeds):
                    self._record_speed(train_id, 0.0)
            self._snapshot = TrackSnapshot(
                self._snapshot.tick,
                self._snapshot.time_seconds,
                bool(enabled),
                self._snapshot.trains,
                self._snapshot.occupied_blocks,
                self._snapshot.turnouts,
            )
        return result

    def bind_feedback(self, module_address: int, input_number: int, block_id: str) -> None:
        """Map one R-BUS contact to a layout block for occupancy safety."""

        if not 1 <= int(module_address) <= 255:
            raise ValueError("module_address must be between 1 and 255")
        if not 1 <= int(input_number) <= 8:
            raise ValueError("input_number must be between 1 and 8")
        if not str(block_id).strip():
            raise ValueError("block_id is required")
        self._feedback_map[(int(module_address), int(input_number))] = str(block_id).strip()

    @property
    def feedback_map(self) -> Mapping[tuple[int, int], str]:
        """Return the configured contact-to-block mapping."""

        return dict(self._feedback_map)

    def feedback_groups(self) -> tuple[int, ...]:
        """Return R-BUS group indexes needed by the configured contacts."""

        return tuple(sorted({(module_address - 1) // 10 for module_address, _ in self._feedback_map}))

    @property
    def feedback_healthy(self) -> bool:
        """Whether the latest configured feedback poll completed successfully."""

        return self._feedback_healthy

    @property
    def feedback_error(self) -> str:
        """Return the latest feedback error, if any."""

        return self._feedback_error

    def poll_feedback(self, groups: Iterable[int] = (0,)) -> tuple[CommandResult, ...]:
        """Poll R-BUS groups and update occupancy without inventing train IDs.

        A contact is represented as ``sensor:<module>:<input>``.  Dispatching
        treats these occupants as protected physical occupancy; a later RailCom
        or application-level train identification layer can replace them with
        known train IDs without changing the safety boundary.
        """

        results: list[CommandResult] = []
        active_by_block: dict[str, list[str]] = {}
        successful_groups: set[int] = set()
        for group in groups:
            result, datasets = self.transport.request_datasets(
                build_rbus_get_data(int(group)),
                expected_header=0x0080,
                command="poll_feedback",
            )
            results.append(result)
            if not result.accepted:
                self._feedback_healthy = False
                self._feedback_error = result.detail or f"R-BUS group {group} poll failed"
                continue
            successful_groups.add(int(group))
            for dataset in datasets:
                feedback = decode_rbus_feedback(dataset)
                for module_address, input_number in feedback.active_contacts:
                    block_id = self._feedback_map.get((module_address, input_number))
                    if block_id is not None:
                        active_by_block.setdefault(block_id, []).append(f"sensor:{module_address}:{input_number}")
        if successful_groups:
            retained = {
                block_id: tuple(values)
                for block_id, values in self._snapshot.occupied_blocks.items()
                if not any((module_address - 1) // 10 in successful_groups for module_address, input_number in self._feedback_map if self._feedback_map[(module_address, input_number)] == block_id)
            }
            retained.update({block_id: tuple(sorted(values)) for block_id, values in active_by_block.items()})
            self._snapshot = TrackSnapshot(
                self._snapshot.tick,
                self._snapshot.time_seconds,
                self._snapshot.powered,
                self._snapshot.trains,
                retained,
                self._snapshot.turnouts,
            )
        if results and all(result.accepted for result in results):
            self._feedback_healthy = True
            self._feedback_error = ""
        return tuple(results)

    def set_turnout_by_address(self, address: int, *, active: bool = True, output: int = 0) -> CommandResult:
        return self.transport.send_dataset(build_set_turnout(address, active=active, output=output), command="set_turnout")
