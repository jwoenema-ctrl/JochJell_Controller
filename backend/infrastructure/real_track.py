"""Track-system adapter that translates normalized commands to Z21 LAN packets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .interfaces import CommandResult, ConnectionStatus, TrackSnapshot
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
        return removed

    def check_connection(self) -> ConnectionStatus:
        status = self.transport.check_connection()
        self._snapshot = TrackSnapshot(self._snapshot.tick, self._snapshot.time_seconds, status.connected, self._snapshot.trains, self._snapshot.occupied_blocks, self._snapshot.turnouts)
        return status

    def connection_status(self) -> ConnectionStatus:
        return self.transport.connection_status()

    def get_snapshot(self) -> TrackSnapshot:
        return self._snapshot

    def tick(self, count: int = 1) -> TrackSnapshot:
        if count < 0:
            raise ValueError("count cannot be negative")
        self._snapshot = TrackSnapshot(self._snapshot.tick + count, self._snapshot.time_seconds + count * self.tick_seconds, self._snapshot.powered, self._snapshot.trains, self._snapshot.occupied_blocks, self._snapshot.turnouts)
        return self._snapshot

    def set_train_speed(self, train_id: str, speed: float) -> CommandResult:
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "set_train_speed", f"no DCC address registered for {train_id}")
        return self.set_train_speed_by_address(
            address,
            speed,
            forward=self._train_directions.get(train_id, True),
        )

    def set_train_speed_by_address(self, address: int, speed: float, *, forward: bool = True) -> CommandResult:
        if not 0.0 <= float(speed) <= 1.0:
            raise ValueError("speed must be between 0 and 1")
        dcc_speed = round(float(speed) * 126)
        # In 128-step DCC, value 1 is reserved for emergency stop. Keep a
        # small but non-zero normalized command a normal drive command.
        if dcc_speed == 1:
            dcc_speed = 2
        try:
            packet = build_set_loco_drive(address, dcc_speed, forward=forward)
        except ValueError as exc:
            return CommandResult(False, "set_train_speed", str(exc))
        return self.transport.send_dataset(packet, command="set_loco_drive")

    def stop_train(self, train_id: str) -> CommandResult:
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "stop_train", f"no DCC address registered for {train_id}")
        return self.stop_by_address(address, forward=self._train_directions.get(train_id, True))

    def stop_by_address(self, address: int, *, forward: bool = True) -> CommandResult:
        packet = build_set_loco_drive(address, 0, forward=forward)
        return self.transport.send_dataset(packet, command="stop_train")

    def set_power(self, enabled: bool) -> CommandResult:
        """Switch Z21 track voltage using the LAN X-BUS command."""

        result = self.transport.send_dataset(build_set_track_power(bool(enabled)), command="set_power")
        if result.accepted:
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
