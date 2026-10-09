"""Märklin CS2/CS3 CAN-over-UDP client.

Wire format follows Märklin CAN protocol 2.0, sections 1.2.7, 1.3,
2.1/2.2, 3.4-3.6, 4.1, 5.2 and 6.1. The station's CAN gateway must
send to this computer on UDP 15730; commands go to station UDP 15731.
Source: https://streaming.maerklin.de/public-media/cs2/cs2CAN-Protokoll-2_0.pdf
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import socket
import struct
import threading
import time

from .hardware_network_track import NetworkTrackSystem
from .interfaces import CommandResult, ConnectionState, ConnectionStatus


@dataclass(frozen=True)
class CANFrame:
    command: int
    data: bytes = b""
    response: bool = False
    hash: int = 0x4711

    def encode(self):
        if not 0 <= self.command <= 255 or len(self.data) > 8 or not 0 <= self.hash <= 65535:
            raise ValueError("Invalid CAN frame")
        identifier = (self.command << 17) | (int(self.response) << 16) | self.hash
        return struct.pack("!IB8s", identifier, len(self.data), self.data.ljust(8, b"\0"))

    @classmethod
    def decode(cls, payload):
        if len(payload) != 13:
            raise ValueError("CAN-over-UDP datagram must be 13 bytes")
        identifier, dlc, data = struct.unpack("!IB8s", payload)
        if dlc > 8 or identifier > 0x1FFFFFFF:
            raise ValueError("Invalid CAN identifier or DLC")
        return cls((identifier >> 17) & 255, data[:dlc], bool(identifier & 0x10000), identifier & 65535)


def locomotive_id(address, protocol="dcc"):
    if isinstance(address, bool) or not isinstance(address, int):
        raise ValueError("Decoder address must be an integer")
    protocol = protocol.lower()
    if protocol == "dcc" and 1 <= address <= 16383:
        return 0xC000 + address
    if protocol == "mm" and 1 <= address <= 1023:
        return address
    if protocol == "mfx" and 1 <= address <= 16383:
        return 0x4000 + address
    raise ValueError("Use DCC address 1–16383, Motorola address 1–1023, or station-assigned mfx SID 1–16383")


class MarklinTransport:
    def __init__(self, host, port=15731, *, local_port=15730, timeout=0.5):
        if not str(host).strip() or not 1 <= int(port) <= 65535 or not 0 <= int(local_port) <= 65535 or timeout <= 0:
            raise ValueError("Invalid Märklin network settings")
        self.host, self.port, self.local_port, self.timeout = str(host).strip(), int(port), int(local_port), float(timeout)
        self._socket = None
        self._peer = None
        self._lock = threading.RLock()
        self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint)
        self.powered = False

    @property
    def endpoint(self):
        return f"{self.host}:{self.port} (UDP receive {self.local_port})"

    def _open(self):
        if self._socket is None:
            self._peer = socket.gethostbyname(self.host)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind(("", self.local_port))
                sock.settimeout(self.timeout)
            except OSError:
                sock.close()
                raise
            self._socket = sock

    def close(self):
        with self._lock:
            if self._socket:
                self._socket.close()
            self._socket = None
            self.powered = False
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, checked_at=time.time())

    def connection_status(self):
        return self._status

    def _observe(self, frame):
        if frame.command == 0 and len(frame.data) >= 5:
            if frame.data[4] in (0, 2):
                self.powered = False
            elif frame.data[4] == 1:
                self.powered = True

    def request(self, frame, *, command, match=None):
        with self._lock:
            try:
                self._open()
                # Discard old acknowledgements, but retain observed global power state.
                self._socket.setblocking(False)
                while True:
                    try:
                        old, peer = self._socket.recvfrom(2048)
                        if peer[0] == self._peer:
                            try:
                                self._observe(CANFrame.decode(old))
                            except ValueError:
                                pass
                    except BlockingIOError:
                        break
                self._socket.settimeout(self.timeout)
                self._socket.sendto(frame.encode(), (self._peer, self.port))
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    self._socket.settimeout(max(0.001, deadline - time.monotonic()))
                    raw, peer = self._socket.recvfrom(2048)
                    if peer[0] != self._peer:
                        continue
                    try:
                        reply = CANFrame.decode(raw)
                    except ValueError:
                        continue
                    self._observe(reply)
                    if reply.response and reply.command == frame.command and (match is None or match(reply)):
                        self._status = ConnectionStatus(ConnectionState.CONNECTED, self.endpoint,
                            "CAN gateway response received", time.time())
                        return CommandResult(True, command, "Command station acknowledged", raw), reply
                raise TimeoutError("No matching CAN response")
            except (OSError, TimeoutError) as exc:
                self.powered = False
                self._status = ConnectionStatus(ConnectionState.ERROR, self.endpoint,
                    f"{exc}; check station CAN gateway destination and UDP receive port", time.time())
                return CommandResult(False, command, self._status.detail), None

    def command(self, frame, command):
        return self.request(frame, command=command, match=lambda r: r.data == frame.data)[0]

    def check_connection(self):
        self.request(CANFrame(0x18), command="check_connection", match=lambda r: len(r.data) == 8)
        return self._status


class MarklinTrackSystem(NetworkTrackSystem):
    def __init__(self, host, port=15731, *, local_port=15730, timeout=0.5, tick_seconds=0.1,
                 feedback_map=None, decoder_protocol="dcc", transport=None):
        super().__init__(transport or MarklinTransport(host, port, local_port=local_port, timeout=timeout),
            tick_seconds=tick_seconds, feedback_map=feedback_map, decoder_protocol=decoder_protocol)
        self._turnout_lock = threading.RLock()

    def validate_address(self, address, protocol):
        locomotive_id(address, protocol)

    def _drive(self, address, speed, *, forward, speed_limit=None, protocol="dcc"):
        uid = locomotive_id(address, protocol).to_bytes(4, "big")
        step = round(speed * 1000)
        if speed_limit is not None:
            step = min(step, math.floor(speed_limit * 1000))
        # Direction is a separate acknowledged CAN command. Never send speed
        # after a failed direction request.
        result = self.transport.command(CANFrame(5, uid + bytes([1 if forward else 2])), "set_direction")
        if not result.accepted:
            return result
        if speed > 0 and not self.transport.powered:
            return CommandResult(False, "set_train_speed", "Station reported track power off")
        return self.transport.command(CANFrame(4, uid + step.to_bytes(2, "big")), "set_train_speed")

    def _function(self, address, number, enabled, *, protocol="dcc"):
        return self.transport.command(CANFrame(6, locomotive_id(address, protocol).to_bytes(4, "big")
            + bytes([number, int(enabled)])), "set_loco_function")

    def set_power(self, enabled):
        result = self._observe_result(self.transport.command(CANFrame(0, b"\0\0\0\0" + bytes([int(bool(enabled))])), "set_power"))
        if result.accepted:
            self._snapshot = replace(self._snapshot, powered=bool(enabled))
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
        if not isinstance(address, int) or not 1 <= address <= 2048 or output not in (0, 1):
            return CommandResult(False, "set_turnout", "Accessory address must be 1–2048 and output 0 or 1")
        protocol = decoder_protocol.lower()
        if protocol not in ("dcc", "mm") or (protocol == "mm" and address > 1024):
            return CommandResult(False, "set_turnout", "Unsupported accessory protocol or address")
        # CAN accessory local IDs use zero-based wire addresses.
        uid = (0x3800 if protocol == "dcc" else 0x3000) + address - 1
        off = CANFrame(0x0B, uid.to_bytes(4, "big") + bytes([output, 0]))
        with self._turnout_lock:
            if not active:
                return self._observe_result(self.transport.command(off, "set_turnout"))
            # CAN protocol 2.0 section 4.1: DLC8 switching duration is a
            # 16-bit number of 10ms units. The station terminates this pulse
            # even if the client loses the network before its release packet.
            on = CANFrame(0x0B, uid.to_bytes(4, "big") + bytes([output, 1]) + (10).to_bytes(2, "big"))
            activation = None
            release = None
            try:
                activation = self.transport.command(on, "set_turnout")
                if activation.accepted:
                    time.sleep(0.1)
            finally:
                release = self.transport.command(off, "release_turnout")
            if activation is None or not activation.accepted:
                return self._observe_result(activation or CommandResult(False, "set_turnout", "Activation failed"))
            if not release.accepted:
                return self._observe_result(CommandResult(False, "set_turnout",
                    "Turnout pulse sent, but release was not acknowledged: " + release.detail))
            return self._observe_result(activation)

    def close(self):
        # A station replacement waits for the pending bounded pulse and its
        # release before closing this adapter's receive socket.
        with self._turnout_lock:
            super().close()

    def _read_feedback(self, device, contacts):
        states = {}
        for contact in contacts:
            data = int(device).to_bytes(2, "big") + int(contact).to_bytes(2, "big")
            result, frame = self.transport.request(CANFrame(0x11, data), command="poll_feedback",
                match=lambda r, key=data: len(r.data) == 8 and r.data[:4] == key)
            if not result.accepted:
                return result, {}
            states[contact] = bool(frame.data[5])
        return CommandResult(True, "poll_feedback", "Fresh CAN contact states received"), states
