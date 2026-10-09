"""Lenz LI-USB framed XpressNet adapter for a real serial PC interface.

Wire format: Lenz XpressNet V4.0 and interface 23151 command documentation:
https://www.lenz-elektronik.de/media/0a/d1/4e/1760451943/XpressNet_V40_2.pdf
https://www.lenz-elektronik.de/media/37/8b/2f/1734009949/b_23151.pdf
Commands require a valid reply or LI completion acknowledgment; successful
serial writes alone never count as accepted hardware commands.
"""

from __future__ import annotations

from dataclasses import replace
import math
from threading import RLock
import time

from .hardware_network_track import NetworkTrackSystem
from .interfaces import CommandResult, ConnectionState, ConnectionStatus


def encode_frame(message: bytes, *, broadcast: bool = False) -> bytes:
    if not message or len(message) != (message[0] & 15) + 1:
        raise ValueError("XpressNet message length does not match its header")
    checksum = 0
    for value in message:
        checksum ^= value
    return bytes((255, 253 if broadcast else 254)) + message + bytes((checksum,))


def decoder_bytes(address: int) -> bytes:
    if type(address) is not int or not 1 <= address <= 9999:
        raise ValueError("XpressNet decoder address must be between 1 and 9999")
    return bytes(((address >> 8) | (192 if address >= 100 else 0), address & 255))


class XpressNetSerialTransport:
    def __init__(self, serial_port: str, *, baudrate=57600, timeout=5.0, serial_factory=None):
        if not isinstance(serial_port, str) or not serial_port.strip():
            raise ValueError("Select a serial port for the XpressNet LI-USB interface")
        if type(baudrate) is not int or baudrate not in (9600, 19200, 38400, 57600, 115200):
            raise ValueError("Unsupported serial baud rate")
        if not math.isfinite(float(timeout)) or timeout <= 0:
            raise ValueError("Serial timeout must be positive")
        self.serial_port = serial_port.strip()
        self.baudrate = baudrate
        self.timeout = float(timeout)
        self._serial_factory = serial_factory
        self._serial = None
        self._lock = RLock()
        self._buffer = bytearray()
        self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.serial_port, "Not checked")
        self.powered = False

    def open(self):
        with self._lock:
            if self._serial is not None:
                return
            factory = self._serial_factory
            if factory is None:
                try:
                    import serial
                except ImportError:
                    raise ValueError("XpressNet serial support requires pyserial; install requirements-hardware.txt") from None
                factory = serial.Serial
            self._serial = factory(port=self.serial_port, baudrate=self.baudrate,
                                   timeout=self.timeout, write_timeout=self.timeout,
                                   rtscts=False, dsrdtr=False, xonxoff=False)

    def close(self):
        with self._lock:
            connection, self._serial = self._serial, None
            if connection is not None:
                connection.close()
            self._buffer.clear()
            self.powered = False
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.serial_port, "Closed")

    def connection_status(self):
        return self._status

    def _read_frame(self, deadline):
        while time.monotonic() < deadline:
            while len(self._buffer) >= 3:
                if self._buffer[0] != 255 or self._buffer[1] not in (253, 254):
                    del self._buffer[0]
                    continue
                length = (self._buffer[2] & 15) + 4
                if len(self._buffer) < length:
                    break
                frame = bytes(self._buffer[:length])
                del self._buffer[:length]
                checksum = 0
                for value in frame[2:]:
                    checksum ^= value
                if checksum:
                    raise ValueError("Invalid XpressNet response checksum")
                return frame[1] == 253, frame[2:-1]
            self._serial.timeout = max(.001, deadline - time.monotonic())
            data = self._serial.read(1)
            if not data:
                raise TimeoutError("XpressNet interface did not answer")
            self._buffer.extend(data)
        raise TimeoutError("XpressNet response timed out")

    def exchange(self, message: bytes, *, command: str, predicate, require_connected=True):
        with self._lock:
            packet = encode_frame(message)
            if require_connected and not self._status.connected:
                return CommandResult(False, command, "XpressNet station is not connected", packet), None
            try:
                if self._serial is None:
                    self.open()
                written = self._serial.write(packet)
                if written != len(packet):
                    raise OSError("Incomplete serial write")
                deadline = time.monotonic() + self.timeout
                while True:
                    broadcast, reply = self._read_frame(deadline)
                    if reply in (bytes((97, 0)), bytes((97, 1))):
                        self.powered = reply[1] == 1
                    elif reply in (bytes((97, 2)), bytes((129, 0))):
                        self.powered = False
                    if broadcast:
                        if reply == bytes((1, 5)):
                            raise OSError("Station stopped polling the XpressNet interface")
                        continue
                    if reply[0] == 1 and reply[1] != 4:
                        raise ValueError(f"LI-USB interface rejected the command (code {reply[1]})")
                    if reply in (bytes((97, 128)), bytes((97, 129)), bytes((97, 130))):
                        return CommandResult(False, command, "Station rejected the command or is busy", packet), reply
                    if not predicate(reply):
                        raise ValueError("Unexpected XpressNet response to command")
                    self._status = ConnectionStatus(ConnectionState.CONNECTED, self.serial_port,
                                                    "LI-USB station reply received", time.time())
                    return CommandResult(True, command, "Station acknowledged command", packet), reply
            except (OSError, ValueError) as exc:
                self.powered = False
                self._status = ConnectionStatus(ConnectionState.ERROR, self.serial_port, str(exc), time.time())
                return CommandResult(False, command, str(exc), packet), None

    def check_connection(self):
        result, reply = self.exchange(bytes((33, 36)), command="check_connection",
            predicate=lambda value: len(value) == 3 and value[:2] == bytes((98, 34)), require_connected=False)
        if result.accepted:
            # Emergency off, emergency stop and programming modes inhibit power.
            self.powered = not bool(reply[2] & 0xCB)
        return self._status

    def command(self, message, command):
        return self.exchange(message, command=command,
                             predicate=lambda reply: reply == bytes((1, 4)))[0]


class XpressNetTrackSystem(NetworkTrackSystem):
    def __init__(self, host=None, *, serial_port="", baudrate=57600, timeout=5.0,
                 feedback_map=None, decoder_protocol="dcc", serial_factory=None, tick_seconds=.1):
        if decoder_protocol != "dcc":
            raise ValueError("XpressNet profile supports DCC decoder addresses")
        for module, contact in (feedback_map or {}):
            self._validate_feedback(module, contact)
        transport = XpressNetSerialTransport(serial_port, baudrate=baudrate, timeout=timeout,
                                            serial_factory=serial_factory)
        transport.open()
        super().__init__(transport, feedback_map=feedback_map, decoder_protocol=decoder_protocol,
                         tick_seconds=tick_seconds)

    def check_connection(self):
        status = self.transport.check_connection()
        self._snapshot = replace(self._snapshot, powered=self._snapshot.powered and status.connected and self.transport.powered)
        return status

    def validate_address(self, address, protocol):
        if protocol != "dcc":
            raise ValueError("XpressNet profile supports DCC decoder addresses")
        decoder_bytes(address)

    def _drive(self, address, speed, *, forward, speed_limit=None, protocol="dcc"):
        self.validate_address(address, protocol)
        if not math.isfinite(speed) or not 0 <= speed <= 1:
            raise ValueError("Speed must be between 0 and 1")
        if speed > 0 and not self._snapshot.powered:
            return CommandResult(False, "set_train_speed", "Track power is off")
        if speed_limit is not None:
            speed = min(speed, speed_limit)
        # 0 is stop, 1 emergency stop; drive steps run from 2 through 127.
        step = 0 if speed == 0 else max(2, min(127, 1 + round(speed * 126)))
        result = self.transport.command(bytes((228, 19)) + decoder_bytes(address)
                                        + bytes((step | (128 if forward else 0),)), "set_train_speed")
        if speed > 0 and result.accepted and not self.transport.powered:
            self._snapshot = replace(self._snapshot, powered=False)
            return CommandResult(False, "set_train_speed", "Station reported track power off", result.payload)
        return result

    def _function(self, address, number, enabled, *, protocol="dcc"):
        if not 0 <= number <= 28:
            return CommandResult(False, "set_loco_function", "This XpressNet profile supports F0–F28")
        if not self._snapshot.powered:
            return CommandResult(False, "set_loco_function", "Track power is off")
        with self.transport._lock:
            query = bytes((227, 0 if number <= 12 else 9)) + decoder_bytes(address)
            result, reply = self.transport.exchange(query, command="read_function_group",
                predicate=lambda value: (len(value) == 5 and value[0] == 228) if number <= 12
                else (len(value) == 4 and value[:2] == bytes((227, 82))))
            if not result.accepted:
                return result
            if number <= 4:
                command, current, bit = 32, reply[3] & 31, 4 if number == 0 else number - 1
            elif number <= 8:
                command, current, bit = 33, reply[4] & 15, number - 5
            elif number <= 12:
                command, current, bit = 34, (reply[4] >> 4) & 15, number - 9
            elif number <= 20:
                command, current, bit = 35, reply[2], number - 13
            else:
                command, current, bit = 40, reply[3], number - 21
            value = current | (1 << bit) if enabled else current & ~(1 << bit)
            return self.transport.command(bytes((228, command)) + decoder_bytes(address)
                                          + bytes((value,)), "set_loco_function")

    def set_power(self, enabled):
        if not enabled:
            for train in tuple(self._train_addresses):
                self.stop_train(train)
        result, reply = self.transport.exchange(bytes((33, 129 if enabled else 128)), command="set_power",
            predicate=lambda value: value in (bytes((97, 0)), bytes((97, 1))))
        if result.accepted and bool(reply[1]) != bool(enabled):
            self._snapshot = replace(self._snapshot, powered=False)
            return CommandResult(False, "set_power", "Station rejected the requested power state", result.payload)
        if result.accepted:
            status = self.transport.check_connection()
            if not status.connected or self.transport.powered != bool(enabled):
                self._snapshot = replace(self._snapshot, powered=False)
                return CommandResult(False, "set_power", "Station power change was not confirmed")
            self._snapshot = replace(self._snapshot, powered=bool(enabled))
        elif not enabled:
            self._snapshot = replace(self._snapshot, powered=False)
        return self._observe_result(result)

    def set_turnout_by_address(self, address, *, active=True, output=0):
        if type(address) is not int or not 1 <= address <= 1024 or output not in (0, 1):
            raise ValueError("XpressNet turnout address must be 1–1024 and output 0 or 1")
        if not self._snapshot.powered:
            return CommandResult(False, "set_turnout", "Track power is off")
        group, offset = divmod(address - 1, 4)
        with self.transport._lock:
            value = 128 | (8 if active else 0) | (offset << 1) | output
            result = self.transport.command(bytes((82, group, value)), "set_turnout")
            if active:
                if result.accepted:
                    time.sleep(.1)
                release = self.transport.command(bytes((82, group, value & ~8)), "release_turnout")
                if not release.accepted:
                    return release
            if result.accepted:
                self._snapshot = replace(self._snapshot, turnouts={**self._snapshot.turnouts, str(address): output})
            return result

    @staticmethod
    def _validate_feedback(module, contact):
        if type(module) is not int or not 0 <= module <= 127 or type(contact) is not int or not 1 <= contact <= 8:
            raise ValueError("XpressNet feedback module must be 0–127 and contact 1–8")

    def bind_feedback(self, module_address, input_number, block_id):
        self._validate_feedback(module_address, input_number)
        return super().bind_feedback(module_address, input_number, block_id)

    def _read_feedback(self, device, contacts):
        states = {}
        result = CommandResult(False, "poll_feedback", "No contacts configured")
        for nibble in sorted({(contact - 1) // 4 for contact in contacts}):
            result, reply = self.transport.exchange(bytes((66, device, 128 | nibble)), command="poll_feedback",
                predicate=lambda value: len(value) == 3 and value[0] == 66 and value[1] == device
                    and value[2] & 0x60 == 0x40 and (value[2] >> 4) & 1 == nibble)
            if not result.accepted:
                return result, {}
            for bit in range(4):
                states[1 + nibble * 4 + bit] = bool(reply[2] & (1 << bit))
        return result, states
