"""Shared physical-track state and safety policy for network command stations.

Only confirmed commands update this adapter's commanded state. Occupancy is
contact feedback, never an inferred train identity or simulated movement.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

from .interfaces import CommandResult
from .real_track import Z21TrackSystem


class NetworkTrackSystem(Z21TrackSystem):
    """Reuse position, route and speed-limit policy while replacing the wire protocol."""

    def __init__(self, transport, *, tick_seconds=0.1, feedback_map=None, decoder_protocol="dcc"):
        super().__init__(transport, tick_seconds=tick_seconds, feedback_map=feedback_map)
        self._default_protocol = decoder_protocol
        self._train_protocols: dict[str, str] = {}
        self._contact_states: dict[tuple[int, int], bool] = {}
        for (device, contact), block in tuple(self._feedback_map.items()):
            self.bind_feedback(device, contact, block)

    def validate_address(self, address: int, protocol: str) -> None:
        raise NotImplementedError

    def register_train(self, train_id: str, address: int, *, forward=True, decoder_protocol=None):
        protocol = (decoder_protocol or self._default_protocol).lower()
        self.validate_address(address, protocol)
        if not str(train_id).strip():
            raise ValueError("train_id is required")
        self._train_addresses[train_id] = address
        self._train_directions[train_id] = bool(forward)
        self._train_protocols[train_id] = protocol

    bind_train = register_train

    def unregister_train(self, train_id):
        self._train_protocols.pop(train_id, None)
        return super().unregister_train(train_id)

    def _drive(self, address, speed, *, forward, speed_limit=None, protocol="dcc"):
        raise NotImplementedError

    def _function(self, address, number, enabled, *, protocol="dcc"):
        raise NotImplementedError

    def _observe_result(self, result):
        if not self.transport.connection_status().connected:
            self._snapshot = replace(self._snapshot, powered=False)
            self._feedback_healthy = not bool(self._feedback_map)
            if self._feedback_map:
                self._feedback_error = result.detail or "Command station disconnected"
        return result

    def set_train_speed(self, train_id, speed):
        if not 0 <= float(speed) <= 1:
            raise ValueError("speed must be between 0 and 1")
        if float(speed) > 0 and not self.get_snapshot().powered:
            return CommandResult(False, "set_train_speed", "Track power is off")
        address = self._train_addresses.get(train_id)
        if address is None:
            return CommandResult(False, "set_train_speed", "No decoder address registered")
        effective = self._limited_speed(train_id, float(speed))
        result = self._observe_result(self._drive(address, effective,
            forward=self.get_train_direction(train_id), protocol=self._train_protocols[train_id],
            speed_limit=self._limited_speed(train_id, 1) if self.get_train_speed_limit(train_id) is not None else None))
        self._requested_speeds[train_id] = float(speed) if result.accepted else 0
        if result.accepted:
            self._record_speed(train_id, effective)
        return result

    def set_train_speed_by_address(self, address, speed, *, forward=True, speed_limit=None, decoder_protocol=None):
        source = getattr(self, "computer_feedback", None)
        if speed > 0 and source is not None and not source.healthy:
            return CommandResult(False, "set_train_speed", source.error)
        protocol = decoder_protocol or self._default_protocol
        self.validate_address(address, protocol)
        if not 0 <= float(speed) <= 1:
            raise ValueError("speed must be between 0 and 1")
        if float(speed) > 0 and not self.get_snapshot().powered:
            return CommandResult(False, "set_train_speed", "Track power is off")
        return self._observe_result(self._drive(address, float(speed), forward=forward,
            speed_limit=speed_limit, protocol=protocol))

    def stop_train(self, train_id):
        address = self._train_addresses.get(train_id)
        self._requested_speeds[train_id] = 0
        if address is None:
            return CommandResult(False, "stop_train", "No decoder address registered")
        result = self._observe_result(self._drive(address, 0, forward=self.get_train_direction(train_id),
            protocol=self._train_protocols[train_id]))
        if result.accepted:
            self._record_speed(train_id, 0)
        return result

    def stop_by_address(self, address, *, forward=True, decoder_protocol=None):
        return self.set_train_speed_by_address(address, 0, forward=forward, decoder_protocol=decoder_protocol)

    def set_train_direction(self, train_id, *, forward):
        if train_id not in self._train_addresses:
            return CommandResult(False, "set_direction", "No decoder address registered")
        if self._requested_speeds.get(train_id, 0) or self.get_effective_speed(train_id):
            return CommandResult(False, "set_direction", "Stop the train before changing direction")
        result = self._observe_result(self._drive(self._train_addresses[train_id], 0, forward=forward,
            protocol=self._train_protocols[train_id]))
        if result.accepted:
            self._train_directions[train_id] = bool(forward)
            self._snapshot = replace(self._snapshot, trains=tuple(
                replace(m, direction=1 if forward else -1) if m.train_id == train_id else m
                for m in self._snapshot.trains))
        return result

    def set_train_function(self, train_id, function_number, *, enabled):
        if train_id not in self._train_addresses:
            return CommandResult(False, "set_loco_function", "No decoder address registered")
        result = self.set_function_by_address(self._train_addresses[train_id], function_number,
            enabled=enabled, decoder_protocol=self._train_protocols[train_id])
        if result.accepted:
            self._train_functions.setdefault(train_id, {})[function_number] = bool(enabled)
        return result

    def set_function_by_address(self, address, function_number, *, enabled, decoder_protocol=None):
        protocol = decoder_protocol or self._default_protocol
        try:
            self.validate_address(address, protocol)
        except ValueError as exc:
            return CommandResult(False, "set_loco_function", str(exc))
        if isinstance(function_number, bool) or not isinstance(function_number, int) or not 0 <= function_number <= 31:
            return CommandResult(False, "set_loco_function", "Function number must be between 0 and 31")
        return self._observe_result(self._function(address, function_number, bool(enabled), protocol=protocol))

    def bind_feedback(self, module_address, input_number, block_id):
        if not 0 <= int(module_address) <= 65535 or not 1 <= int(input_number) <= 65535:
            raise ValueError("Feedback device and contact must be 16-bit identifiers")
        if not str(block_id).strip():
            raise ValueError("block_id is required")
        self._feedback_map[(int(module_address), int(input_number))] = str(block_id).strip()
        self._feedback_healthy = False

    def feedback_groups(self):
        return tuple(sorted({device for device, _ in self._feedback_map}))

    def _read_feedback(self, device, contacts):
        raise NotImplementedError

    def poll_feedback(self, groups: Iterable[int] | None = None):
        groups = self.feedback_groups() if groups is None else tuple(groups)
        results = []
        for device in groups:
            contacts = [contact for mod, contact in self._feedback_map if mod == device]
            if not contacts:
                continue
            result, states = self._read_feedback(device, contacts)
            results.append(result)
            if result.accepted and all(contact in states for contact in contacts):
                for contact in contacts:
                    self._contact_states[(device, contact)] = bool(states[contact])
            else:
                if result.accepted:
                    result = CommandResult(False, "poll_feedback", "Incomplete feedback response")
                    results[-1] = result
                self._feedback_error = result.detail
        occupied: dict[str, list[str]] = {}
        for key, block in self._feedback_map.items():
            if self._contact_states.get(key, False):
                occupied.setdefault(block, []).append(f"sensor:{key[0]}:{key[1]}")
        self._snapshot = replace(self._snapshot, occupied_blocks={k: tuple(sorted(v)) for k, v in occupied.items()})
        self._feedback_healthy = (not self._feedback_map or (bool(results) and all(r.accepted for r in results)
            and set(groups) >= set(self.feedback_groups())
            and all(key in self._contact_states for key in self._feedback_map)))
        if self._feedback_healthy:
            self._feedback_error = ""
        return tuple(results)

    def read_power_telemetry(self):
        return {"available": False, "reason": "Power measurements are not provided by this adapter"}

    def probe_train_address(self, address):
        return CommandResult(False, "probe_train_address", "Physical decoder presence detection is not supported")

    def read_cv(self, train_id, cv, *, target="programming_track"):
        return CommandResult(False, "read_cv", "Decoder programming is not supported by this adapter"), None

    def write_cv(self, train_id, cv, value, *, target="programming_track"):
        return CommandResult(False, "write_cv", "Decoder programming is not supported by this adapter")

    def program_dcc_address(self, train_id, address, *, target="programming_track"):
        return CommandResult(False, "program_dcc_address", "Decoder programming is not supported by this adapter")

    def close(self):
        self.transport.close()
        self._snapshot = replace(self._snapshot, powered=False)
