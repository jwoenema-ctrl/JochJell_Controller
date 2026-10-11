"""Independent occupancy and optional turnout bridge over USB serial or TCP.

Bridges report newline-delimited JSON snapshots. Turnout commands require a
matching acknowledgement; locomotive and power commands never use this link.
"""
from __future__ import annotations

import json
import math
import socket
import threading
import time
import uuid

from .interfaces import CommandResult


DEFAULT_COMPUTER_FEEDBACK = {"transport": "serial", "serial_port": "", "baudrate": 115200,
                             "host": "127.0.0.1", "port": 5550, "timeout_s": 3.0}


def validate_computer_feedback(value, current=None):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_COMPUTER_FEEDBACK):
        raise ValueError("invalid computer detector connection settings")
    result = {**DEFAULT_COMPUTER_FEEDBACK, **(current or {}), **value}
    if result["transport"] not in ("serial", "tcp"):
        raise ValueError("choose USB / serial or network TCP")
    for key in ("serial_port", "host"):
        if not isinstance(result[key], str) or len(result[key]) > 255 or any(ord(c) < 32 for c in result[key]):
            raise ValueError(f"invalid detector {key}")
        result[key] = result[key].strip()
    if not result["host"]:
        raise ValueError("detector host is required")
    for key, minimum, maximum in (("port", 1, 65535), ("baudrate", 1200, 2000000)):
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError(f"detector {key} must be {minimum}–{maximum}")
    timeout = result["timeout_s"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not .5 <= timeout <= 60:
        raise ValueError("detector timeout must be 0.5–60 seconds")
    return result


class ComputerFeedback:
    MAX_FRAME = 65536

    def __init__(self, config=None, *, clock=time.monotonic):
        self.config = validate_computer_feedback(config or {})
        self.mapping = {}
        self.turnouts = {}
        self._turnout_states = {}
        self._turnout_error = ""
        self._pending = {}
        self._write_lock = threading.Lock()
        self._clock = clock
        self._lock = threading.RLock()
        self._stream = None
        self._worker = None
        self._stop = threading.Event()
        self._connected = False
        self._states = {}
        self._received_at = None
        self._error = "Computer detectors are disconnected"

    def replace_mapping(self, mapping):
        with self._lock:
            if self.mapping != mapping:
                self.mapping = dict(mapping)
                self._states = {}
                self._received_at = None
                self._error = "Awaiting a complete detector snapshot"

    def replace_turnouts(self, mapping):
        with self._lock:
            self._turnout_states = {key: value for key, value in self._turnout_states.items()
                                    if key in mapping and self.turnouts.get(key) == mapping[key]}
            self.turnouts = {key: dict(value) for key, value in mapping.items()}

    def _accept_ack(self, frame):
        with self._lock:
            request_id = frame.get("request_id")
            pending = self._pending.get(request_id) if isinstance(request_id, str) else None
            if pending is None or pending["event"].is_set():
                return
            command = pending["command"]
            if (type(frame.get("accepted")) is not bool
                    or any(type(frame.get(key)) is not type(command[key]) or frame.get(key) != command[key]
                           for key in ("module", "output", "position"))):
                return  # Wrong, incomplete and late acknowledgements cannot confirm a switch.
            pending["accepted"] = frame["accepted"]
            pending["detail"] = str(frame.get("detail", ""))[:200]
            pending["event"].set()

    def send_turnout(self, turnout_id, position):
        if position not in ("straight", "diverging"):
            raise ValueError("choose straight or diverging")
        with self._write_lock:
            with self._lock:
                row = self.turnouts.get(turnout_id)
                if row is None or not self._connected or self._stream is None:
                    return CommandResult(False, "set_turnout", "Computer switch bridge is disconnected or this switch is not mapped")
                wire_position = ("diverging" if position == "straight" else "straight") if row["inverted"] else position
                command = {"type": "set_turnout", "request_id": uuid.uuid4().hex, "module": row["module"],
                           "output": row["output"], "position": wire_position, "pulse_ms": row["pulse_ms"]}
                pending = {"event": threading.Event(), "command": command, "accepted": False, "detail": ""}
                self._pending[command["request_id"]] = pending
                self._turnout_states.pop(turnout_id, None)
                stream = self._stream
            try:
                wire = (json.dumps(command, separators=(",", ":")) + "\n").encode("utf-8")
                if self.config["transport"] == "tcp":
                    stream.sendall(wire)
                elif stream.write(wire) != len(wire):
                    raise OSError("incomplete serial switch command")
                if not pending["event"].wait(timeout=min(self.config["timeout_s"], 3.0)):
                    pending["detail"] = "Switch acknowledgement timed out; position is unconfirmed"
            except (OSError, ValueError) as exc:
                pending["detail"] = f"Switch command failed: {exc}"
            finally:
                with self._lock:
                    self._pending.pop(command["request_id"], None)
                    accepted = pending["accepted"] and self._connected
                    self._turnout_error = "" if accepted else pending["detail"] or "Switch command rejected; position is unconfirmed"
                    if accepted:
                        self._turnout_states[turnout_id] = position
            return CommandResult(accepted, "set_turnout", self._turnout_error)

    def ingest(self, frame):
        """Validate a complete snapshot atomically; partial frames cannot clear blocks."""
        try:
            if isinstance(frame, (bytes, str)):
                if len(frame) > self.MAX_FRAME:
                    raise ValueError("detector frame is too large")
                frame = json.loads(frame)
            if isinstance(frame, dict) and frame.get("type") == "turnout_ack":
                self._accept_ack(frame)
                return
            if not isinstance(frame, dict) or set(frame) != {"contacts"} or not isinstance(frame["contacts"], list) or len(frame["contacts"]) > 4096:
                raise ValueError("expected a contacts snapshot")
            states = {}
            for row in frame["contacts"]:
                if not isinstance(row, dict) or set(row) != {"module", "input", "occupied"}:
                    raise ValueError("each contact needs module, input and occupied")
                module, contact = row["module"], row["input"]
                if type(module) is not int or type(contact) is not int or not 1 <= module <= 65535 or not 1 <= contact <= 65535 or type(row["occupied"]) is not bool:
                    raise ValueError("invalid detector address or occupancy value")
                key = module, contact
                if key in states:
                    raise ValueError("duplicate detector contact")
                states[key] = row["occupied"]
            with self._lock:
                if not self.mapping.keys() <= states.keys():
                    raise ValueError("snapshot is missing mapped detector contacts")
                self._states = states
                self._received_at = self._clock()
                self._error = ""
        except (ValueError, TypeError, UnicodeError) as exc:
            with self._lock:
                self._received_at = None
                self._error = f"Invalid detector data: {exc}"
            raise ValueError(self._error) from exc

    def _healthy(self):
        return (self._connected and self._received_at is not None
                and self._clock() - self._received_at <= self.config["timeout_s"]
                and self.mapping.keys() <= self._states.keys())

    @property
    def healthy(self):
        with self._lock:
            inputs_ready = self._healthy() or not self.mapping
            switches_ready = not self.turnouts or (self._healthy() and self.turnouts.keys() <= self._turnout_states.keys())
            return inputs_ready and switches_ready

    @property
    def error(self):
        with self._lock:
            if self.mapping and not self._healthy():
                return self._error or "Detector readings are stale"
            if self.turnouts and self._connected and not self._healthy():
                return self._error or "Computer bridge heartbeat is stale"
            if self.turnouts and not (self._connected and self.turnouts.keys() <= self._turnout_states.keys()):
                return self._turnout_error or "Computer switch positions are unconfirmed; set each mapped switch after connecting"
            if self.turnouts and self._connected and not self.mapping:
                return ""
            return "" if self._healthy() else self._error or "Detector readings are stale"

    def occupied_blocks(self):
        with self._lock:
            healthy = self._healthy()
            occupied = {}
            for (module, contact), block in self.mapping.items():
                if not healthy or self._states.get((module, contact), True):
                    occupied.setdefault(block, []).append(f"sensor:computer:{module}:{contact}" if healthy else f"sensor:computer:unknown:{module}:{contact}")
            return {block: tuple(values) for block, values in occupied.items()}

    def payload(self):
        with self._lock:
            ready = self.healthy if self.mapping or self.turnouts else self._healthy()
            return {"config": dict(self.config), "connected": self._connected, "healthy": ready,
                    "error": self.error, "mapped_contacts": len(self.mapping),
                    "occupied_blocks": self.occupied_blocks(),
                    "age_s": None if self._received_at is None else round(max(0, self._clock() - self._received_at), 2),
                    "mapped_switches": len(self.turnouts), "switch_states": dict(self._turnout_states)}

    def connect(self):
        self.close()
        try:
            if self.config["transport"] == "tcp":
                stream = socket.create_connection((self.config["host"], self.config["port"]), timeout=2)
                stream.settimeout(.25)
            else:
                if not self.config["serial_port"]:
                    raise ValueError("choose the USB / serial detector port")
                try:
                    import serial
                except ImportError as exc:
                    raise ValueError("USB detectors require pyserial; install requirements-hardware.txt") from exc
                stream = serial.Serial(self.config["serial_port"], self.config["baudrate"], timeout=.25, write_timeout=.5)
        except (OSError, ValueError) as exc:
            self._error = f"Detector connection failed: {exc}"
            raise ValueError(self._error) from exc
        with self._lock:
            self._stream = stream
            self._stop = threading.Event()
            self._connected = True
            self._error = "Awaiting a complete detector snapshot"
        self._worker = threading.Thread(target=self._receive, args=(stream, self._stop), name="computer-detectors", daemon=True)
        self._worker.start()

    def _receive(self, stream, stop):
        buffer = b""
        try:
            while not stop.is_set():
                try:
                    chunk = stream.recv(8192) if self.config["transport"] == "tcp" else stream.read(max(1, min(stream.in_waiting, 8192)))
                except socket.timeout:
                    continue
                if not chunk:
                    if self.config["transport"] == "tcp":
                        raise OSError("detector bridge closed the connection")
                    continue
                buffer += chunk
                while b"\n" in buffer:
                    frame, buffer = buffer.split(b"\n", 1)
                    if frame.strip():
                        try:
                            self.ingest(frame)
                        except ValueError:
                            pass  # Keep receiving; a later complete snapshot can recover.
                if len(buffer) > self.MAX_FRAME:
                    raise ValueError("detector frame exceeds 64 KiB")
        except (OSError, ValueError) as exc:
            with self._lock:
                self._error = f"Detector connection lost: {exc}"
        finally:
            with self._lock:
                self._connected = False
                self._received_at = None
                self._turnout_states.clear()
                for pending in self._pending.values():
                    pending["detail"] = "Computer bridge connection lost"
                    pending["event"].set()
            stream.close()

    def close(self):
        self._stop.set()
        stream, worker = self._stream, self._worker
        if stream is not None:
            stream.close()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1)
        with self._lock:
            self._stream = self._worker = None
            self._connected = False
            self._received_at = None
            self._states = {}
            self._turnout_states.clear()
            self._turnout_error = ""
            self._error = "Computer detectors are disconnected"
