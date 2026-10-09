"""ESU ECoS TCP PC-interface client (port 15471).

Commands and reply framing follow ESU's PC interface specification:
https://www.esu.eu/uploads/tx_esudownloads/ECoS_PC-Schnittstellenbeschreibung_ESUKG_DE_Auflage_I.pdf
Locomotives are station objects, not raw DCC packet addresses. Control is
requested without `force`, preserving ownership by a station or hand controller.
"""

from __future__ import annotations

from dataclasses import replace
import math
import re
import socket
import threading
import time

from .hardware_network_track import NetworkTrackSystem
from .interfaces import CommandResult, ConnectionState, ConnectionStatus


def parse_properties(lines):
    objects = {}
    for line in lines:
        match = re.match(r"^(\d+)\s*(.*)$", line.strip())
        if match:
            objects.setdefault(int(match[1]), {}).update({key.lower(): val
                for key, val in re.findall(r"(\w+)\[([^\]]*)\]", match[2])})
    return objects


class ECoSTransport:
    def __init__(self, host, port=15471, *, timeout=0.5):
        if not str(host).strip() or not 1 <= int(port) <= 65535 or timeout <= 0:
            raise ValueError("Invalid ECoS network settings")
        self.host, self.port, self.timeout = str(host).strip(), int(port), float(timeout)
        self._socket = None
        self._buffer = b""
        self._lock = threading.RLock()
        self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint)
        self.generation = 0
        self.powered = False

    @property
    def endpoint(self):
        return f"{self.host}:{self.port}"

    def _open(self):
        if self._socket is None:
            self._socket = socket.create_connection((self.host, self.port), self.timeout)
            self._socket.settimeout(self.timeout)
            self._buffer = b""
            self.generation += 1

    def _disconnect(self):
        if self._socket:
            self._socket.close()
        self._socket = None
        self._buffer = b""
        self.powered = False

    def close(self):
        with self._lock:
            self._disconnect()
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, checked_at=time.time())

    def connection_status(self):
        return self._status

    def _readline(self, deadline):
        while b"\n" not in self._buffer:
            self._socket.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = self._socket.recv(4096)
            if not chunk:
                raise ConnectionError("ECoS closed the connection")
            self._buffer += chunk
            if len(self._buffer) > 1024 * 1024:
                raise ValueError("ECoS response exceeded buffer limit")
            if time.monotonic() >= deadline:
                raise TimeoutError("ECoS response timeout")
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.rstrip(b"\r").decode("utf-8", errors="strict")

    def request(self, command):
        if "\n" in command or "\r" in command or len(command.encode("utf-8")) >= 1024:
            raise ValueError("Invalid or oversized ECoS command")
        with self._lock:
            try:
                self._open()
                self._socket.sendall((command + "\n").encode("utf-8"))
                deadline = time.monotonic() + self.timeout
                header = None
                lines = []
                while time.monotonic() < deadline:
                    line = self._readline(deadline)
                    if line.startswith(("<REPLY ", "<EVENT ")) and line.endswith(">"):
                        header, lines = line, []
                    elif line.startswith("<END "):
                        end = re.fullmatch(r"<END (\d+) \((.*?)\)>", line)
                        if end is None or header is None:
                            raise ValueError("Malformed ECoS reply")
                        props = parse_properties(lines)
                        status = props.get(1, {}).get("status")
                        if status:
                            self.powered = status.upper() == "GO"
                        expected = "<REPLY " + command + ">"
                        if re.sub(r"\s+", "", header) != re.sub(r"\s+", "", expected):
                            header, lines = None, []
                            continue
                        self._status = ConnectionStatus(ConnectionState.CONNECTED, self.endpoint,
                            "ECoS reply received", time.time())
                        accepted = int(end[1]) == 0
                        return CommandResult(accepted, command,
                            "Command station acknowledged" if accepted else f"ECoS error {end[1]}: {end[2]}"), props
                    elif header is not None:
                        lines.append(line)
                raise TimeoutError("No matching ECoS reply")
            except (OSError, ValueError, UnicodeError) as exc:
                self._disconnect()
                self._status = ConnectionStatus(ConnectionState.ERROR, self.endpoint, str(exc), time.time())
                return CommandResult(False, command, str(exc)), {}

    def check_connection(self):
        result, props = self.request("get(1, status)")
        if result.accepted and props.get(1, {}).get("status", "").upper() not in ("GO", "STOP", "SHUTDOWN"):
            self._disconnect()
            self._status = ConnectionStatus(ConnectionState.ERROR, self.endpoint,
                "ECoS did not return a valid station status", time.time())
        return self._status


class ECoSTrackSystem(NetworkTrackSystem):
    def __init__(self, host, port=15471, *, timeout=0.5, tick_seconds=0.1, feedback_map=None,
                 decoder_protocol="dcc", transport=None):
        super().__init__(transport or ECoSTransport(host, port, timeout=timeout),
            tick_seconds=tick_seconds, feedback_map=feedback_map, decoder_protocol=decoder_protocol)
        self._controlled = set()
        self._generation = -1
        self._control_lock = threading.RLock()

    def validate_address(self, address, protocol):
        if isinstance(address, bool) or not isinstance(address, int):
            raise ValueError("Decoder address must be an integer")
        maximum = {"dcc": 16383, "mm": 255, "mfx": 65535}.get(protocol)
        minimum = 1000 if protocol == "mfx" else 1
        if maximum is None or not minimum <= address <= maximum:
            raise ValueError("Use DCC address 1–16383, Motorola address 1–255, or an existing mfx/M4 station object ID")

    def _resolve(self, address, protocol):
        self.validate_address(address, protocol)
        if protocol == "mfx":
            result, objects = self.transport.request(f"get({address}, protocol)")
            if not result.accepted:
                return result, None
            if objects.get(address, {}).get("protocol", "").upper() not in ("M4", "MFX"):
                return CommandResult(False, "resolve_loco", "Station object is not an mfx/M4 locomotive"), None
            return result, address
        result, objects = self.transport.request("queryObjects(10, addr, protocol)")
        if not result.accepted:
            return result, None
        prefix = "DCC" if protocol == "dcc" else "MM"
        found = [oid for oid, props in objects.items() if props.get("addr") == str(address)
            and props.get("protocol", "").upper().startswith(prefix)]
        if len(found) > 1:
            return CommandResult(False, "resolve_loco", "Several station locomotives use this address and protocol"), None
        if found:
            return result, found[0]
        wire_protocol = "DCC128" if protocol == "dcc" else "MM28"
        result, objects = self.transport.request(f"create(10, addr[{address}], protocol[{wire_protocol}], append)")
        try:
            oid = int(objects[10]["id"])
            if not 1000 <= oid <= 65535:
                raise ValueError
        except (KeyError, ValueError):
            return CommandResult(False, "resolve_loco", result.detail if not result.accepted else "No valid locomotive object ID returned"), None
        return result, oid

    def _control(self, oid):
        if self._generation != self.transport.generation:
            self._controlled.clear()
            self._generation = self.transport.generation
        if oid in self._controlled:
            return CommandResult(True, "request_control")
        result, _ = self.transport.request(f"request({oid}, control)")
        if result.accepted:
            self._controlled.add(oid)
        return result

    def _drive(self, address, speed, *, forward, speed_limit=None, protocol="dcc"):
        with self._control_lock:
            return self._drive_locked(address, speed, forward=forward, speed_limit=speed_limit, protocol=protocol)

    def _drive_locked(self, address, speed, *, forward, speed_limit=None, protocol="dcc"):
        result, oid = self._resolve(address, protocol)
        if not result.accepted:
            return result
        result = self._control(oid)
        if not result.accepted:
            return result
        if speed > 0 and not self.transport.powered:
            return CommandResult(False, "set_train_speed", "Station reported track power off")
        step = round(speed * 127)
        if speed_limit is not None:
            step = min(step, math.floor(speed_limit * 127))
        if step == 1:
            step = 0 if speed_limit is not None and speed_limit * 127 < 2 else 2
        result, _ = self.transport.request(f"set({oid}, dir[{0 if forward else 1}], speed[{step}])")
        if result.accepted and speed > 0 and not self.transport.powered:
            return CommandResult(False, "set_train_speed", "Station reported track power off during drive acknowledgement")
        return result

    def _function(self, address, number, enabled, *, protocol="dcc"):
        with self._control_lock:
            return self._function_locked(address, number, enabled, protocol=protocol)

    def _function_locked(self, address, number, enabled, *, protocol="dcc"):
        result, oid = self._resolve(address, protocol)
        if not result.accepted:
            return result
        result = self._control(oid)
        if not result.accepted:
            return result
        return self.transport.request(f"set({oid}, func[{number}, {int(enabled)}])")[0]

    def set_power(self, enabled):
        result, properties = self.transport.request(f"set(1, {'go' if enabled else 'stop'})")
        result = self._observe_result(result)
        if result.accepted:
            reported = properties.get(1, {}).get("status", "").upper()
            actual = reported == "GO" if reported in ("GO", "STOP", "SHUTDOWN") else bool(enabled)
            self.transport.powered = actual
            self._snapshot = replace(self._snapshot, powered=actual)
            if actual != bool(enabled):
                return CommandResult(False, "set_power", "Station reported a different track power state")
            if not enabled:
                self._requested_speeds.clear()
                for train in self._effective_speeds:
                    self._record_speed(train, 0)
        return result

    def check_connection(self):
        status = super().check_connection()
        self._snapshot = replace(self._snapshot, powered=self._snapshot.powered and self.transport.powered and status.connected)
        return status

    def get_snapshot(self):
        if not self.transport.powered:
            self._snapshot = replace(self._snapshot, powered=False)
        return super().get_snapshot()

    def set_turnout_by_address(self, address, *, active=True, output=0, decoder_protocol="dcc"):
        if isinstance(address, bool) or not isinstance(address, int) or not 1 <= address <= 2048 or output not in (0, 1):
            return CommandResult(False, "set_turnout", "Accessory address must be 1–2048 and output 0 or 1")
        if decoder_protocol not in ("dcc", "mm"):
            return CommandResult(False, "set_turnout", "Unsupported accessory protocol")
        if not active:
            # Activation below requires a bounded station PULSE object.
            return CommandResult(True, "set_turnout", "ECoS manages accessory pulse release")
        protocol = "DCC" if decoder_protocol == "dcc" else "MOT"
        with self._control_lock:
            result, objects = self.transport.request("queryObjects(11, addr, protocol)")
            if not result.accepted:
                return self._observe_result(result)
            wanted_protocol = "DCC" if decoder_protocol == "dcc" else "MM"
            matching = [oid for oid, values in objects.items()
                        if values.get("protocol", "").upper() == wanted_protocol
                        and address in [int(value) for value in re.findall(r"\d+", values.get("addr", ""))]]
            if not matching:
                return CommandResult(False, "set_turnout", "Create this accessory in ECoS and configure PULSE mode before operating it")
            for oid in matching:
                result, properties = self.transport.request(f"get({oid}, mode, duration)")
                if not result.accepted:
                    return self._observe_result(result)
                values = properties.get(oid, {})
                if values.get("mode", "").upper() != "PULSE" or values.get("duration", "") not in {"250", "500", "750", "1000", "2500"}:
                    return CommandResult(False, "set_turnout", "Configure this ECoS accessory with PULSE mode and a bounded switching duration")
            return self._observe_result(self.transport.request(f"set(11, switch[{protocol}{address}{'g' if output else 'r'}])")[0])

    def bind_feedback(self, module_address, input_number, block_id):
        if not 1 <= int(module_address) <= 256 or not 1 <= int(input_number) <= 16:
            raise ValueError("ECoS S88 module must be 1–256 and contact 1–16")
        super().bind_feedback(module_address, input_number, block_id)

    def _read_feedback(self, device, contacts):
        if not 1 <= device <= 256 or any(not 1 <= contact <= 16 for contact in contacts):
            return CommandResult(False, "poll_feedback", "Invalid S88 module/contact mapping"), {}
        oid = 100 + device - 1
        result, objects = self.transport.request(f"get({oid}, state, ports)")
        if not result.accepted:
            return result, {}
        try:
            raw = objects[oid]["state"].strip()
            state = int(raw, 16 if raw.lower().startswith("0x") else 10)
            ports = int(objects[oid]["ports"])
            if ports not in (8, 16) or state < 0 or state >= (1 << ports) or any(c > ports for c in contacts):
                raise ValueError
        except (KeyError, ValueError):
            return CommandResult(False, "poll_feedback", "Invalid or incomplete S88 state/port response"), {}
        return result, {contact: bool(state & (1 << (contact - 1))) for contact in contacts}

    def close(self):
        # Closing the TCP connection releases control ownership automatically.
        self._controlled.clear()
        super().close()
