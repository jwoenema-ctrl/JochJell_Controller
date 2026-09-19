"""Optional Z21 LAN transport boundary with explicit, bounded I/O."""

from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol

from .interfaces import CommandResult, ConnectionState, ConnectionStatus


Z21_PORT = 21105
Z21_ALTERNATE_PORT = 21106
Z21_MAX_UDP_PAYLOAD = 1472
Z21_MAX_RESPONSE_DATAGRAMS = 32
LAN_X_HEADER = 0x0040
LAN_LOGOFF = 0x0030
LAN_X_GET_VERSION = 0x21
LAN_X_GET_VERSION_REPLY = 0x63
# Z21-family command stations normally report 0x12. Some z21start firmware
# reports 0x13 while using the same documented LAN_X_GET_VERSION framing.
Z21_COMMAND_STATION_IDS = frozenset((0x12, 0x13))
LAN_X_SET_LOCO_DRIVE = 0xE4
LAN_X_SET_LOCO_FUNCTION = 0xF8
LAN_X_SET_TURNOUT = 0x53
LAN_X_GET_LOCO_INFO = 0xE3
LAN_X_LOCO_INFO = 0xEF
LAN_X_CV_READ = 0x23
LAN_X_CV_WRITE = 0x24
LAN_X_CV_RESULT = 0x64
LAN_X_CV_NACK_SC = 0x61
LAN_X_CV_NACK = 0x61
LAN_X_CV_POM = 0xE6
LAN_RAILCOM_DATACHANGED = 0x88
LAN_RAILCOM_GETDATA = 0x89
LAN_X_SET_TRACK_POWER_OFF = 0x80
LAN_X_SET_TRACK_POWER_ON = 0x81
LAN_RMBUS_DATACHANGED = 0x80
LAN_RMBUS_GETDATA = 0x81


class DatagramSocket(Protocol):
    """Subset of a UDP socket used by :class:`Z21LanTransport`."""

    def settimeout(self, value: float | None) -> None:
        """Set the receive timeout."""

    def connect(self, address: tuple[str, int]) -> None:
        """Associate this UDP socket with the Z21 endpoint."""

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        """Send one datagram."""

    def recvfrom(self, buffer_size: int) -> tuple[bytes, tuple[str, int]]:
        """Receive one datagram."""

    def close(self) -> None:
        """Close the socket."""


@dataclass(frozen=True)
class Z21Dataset:
    """One decoded Z21 record, excluding the two-byte length field."""

    header: int
    data: bytes

    def __post_init__(self) -> None:
        try:
            header = int(self.header)
        except (TypeError, ValueError) as exc:
            raise ValueError("Z21 dataset header must be an integer") from exc
        if not 0 <= header <= 0xFFFF:
            raise ValueError("Z21 dataset header must fit two bytes")
        try:
            data = bytes(self.data)
        except (TypeError, ValueError) as exc:
            raise ValueError("Z21 dataset data must be bytes-like") from exc
        object.__setattr__(self, "header", header)
        object.__setattr__(self, "data", data)

    def encode(self) -> bytes:
        """Encode as DataLen + little-endian Header + Data."""

        length = 4 + len(self.data)
        if length > 0xFFFF:
            raise ValueError("Z21 dataset is too large")
        return struct.pack("<HH", length, self.header) + self.data


@dataclass(frozen=True)
class RBusFeedback:
    """Decoded ten-module R-BUS feedback group."""

    group_index: int
    bitmap: bytes
    active_contacts: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if not 0 <= int(self.group_index) <= 255:
            raise ValueError("group_index must fit one byte")
        if len(self.bitmap) != 10:
            raise ValueError("R-BUS feedback bitmap must contain ten bytes")

    @property
    def module_range(self) -> range:
        """Return the ten feedback-module addresses represented by this group."""

        start = self.group_index * 10 + 1
        return range(start, start + 10)


def encode_dataset(header: int, data: bytes = b"") -> bytes:
    """Encode a Z21 record using the documented little-endian framing."""

    return Z21Dataset(header=header, data=bytes(data)).encode()


def decode_dataset(packet: bytes) -> Z21Dataset:
    """Decode exactly one Z21 record and reject truncated or combined packets."""

    try:
        packet = bytes(packet)
    except (TypeError, ValueError) as exc:
        raise ValueError("packet must be bytes-like") from exc
    if len(packet) < 4:
        raise ValueError("packet is shorter than a Z21 header")
    length, header = struct.unpack_from("<HH", packet)
    if length != len(packet):
        raise ValueError("packet length does not match DataLen")
    return Z21Dataset(header=header, data=packet[4:])


def iter_datasets(packet: bytes) -> Iterator[Z21Dataset]:
    """Decode combined Z21 records from one UDP payload."""

    try:
        packet = bytes(packet)
    except (TypeError, ValueError) as exc:
        raise ValueError("packet must be bytes-like") from exc
    if not packet:
        raise ValueError("combined packet contains no Z21 datasets")
    offset = 0
    while offset < len(packet):
        if len(packet) - offset < 2:
            raise ValueError("combined packet has a truncated DataLen")
        length = struct.unpack_from("<H", packet, offset)[0]
        if length < 4 or offset + length > len(packet):
            raise ValueError("combined packet contains an invalid DataLen")
        yield decode_dataset(packet[offset : offset + length])
        offset += length


def xbus_checksum(data: bytes) -> int:
    """Return the X-BUS XOR checksum for command data."""

    result = 0
    for byte in data:
        result ^= byte
    return result


def encode_xbus(*data: int) -> bytes:
    """Encode an X-BUS command inside the Z21 LAN X-BUS header."""

    if not data:
        raise ValueError("an X-BUS command requires at least one data byte")
    payload = bytes(data)
    return encode_dataset(LAN_X_HEADER, payload + bytes((xbus_checksum(payload),)))


def build_get_version() -> bytes:
    """Build LAN_X_GET_VERSION (0x40/0x21)."""

    return encode_xbus(LAN_X_GET_VERSION, LAN_X_GET_VERSION)


def build_get_loco_info(address: int) -> bytes:
    """Build a Z21 locomotive-info poll/subscription request."""

    address = _validate_loco_address(address)
    address_msb = (address >> 8) & 0x3F
    if address >= 128:
        address_msb |= 0xC0
    return encode_xbus(LAN_X_GET_LOCO_INFO, 0xF0, address_msb, address & 0xFF)


def build_railcom_get_data(address: int) -> bytes:
    """Build a RailCom poll for one saved locomotive address."""

    address = _validate_loco_address(address)
    return encode_dataset(LAN_RAILCOM_GETDATA, bytes((0x01, address & 0xFF, (address >> 8) & 0xFF)))


def _validate_loco_address(address: int) -> int:
    try:
        address = int(address)
    except (TypeError, ValueError) as exc:
        raise ValueError("address must be an integer") from exc
    if not 1 <= address <= 0x3FFF:
        raise ValueError("address must be between 1 and 16383")
    return address


def build_logoff() -> bytes:
    """Build LAN_LOGOFF (0x30), which has no data field."""

    return encode_dataset(LAN_LOGOFF)


def build_set_loco_drive(
    address: int,
    speed: int,
    *,
    forward: bool = True,
    speed_steps: int = 128,
) -> bytes:
    """Build LAN_X_SET_LOCO_DRIVE for a DCC locomotive.

    ``speed`` is the DCC speed value.  For 128 steps the supported normal
    range is 0..126; value 1 is reserved by the protocol for emergency stop.
    """

    address = _validate_loco_address(address)
    if speed_steps not in (14, 28, 128):
        raise ValueError("speed_steps must be 14, 28, or 128")
    max_speed = {14: 15, 28: 31, 128: 126}[speed_steps]
    if not 0 <= speed <= max_speed:
        raise ValueError(f"speed must be between 0 and {max_speed}")
    if speed == 1:
        raise ValueError("speed value 1 is reserved for emergency stop")
    step_code = {14: 0, 28: 2, 128: 3}[speed_steps]
    address_msb = (address >> 8) & 0x3F
    if address >= 128:
        address_msb |= 0xC0
    direction_and_speed = (0x80 if forward else 0) | speed
    return encode_xbus(0xE4, 0x10 | step_code, address_msb, address & 0xFF, direction_and_speed)


def build_set_loco_function(address: int, function_number: int, *, enabled: bool) -> bytes:
    """Build LAN_X_SET_LOCO_FUNCTION for a DCC locomotive function."""

    address = _validate_loco_address(address)
    if not 0 <= int(function_number) <= 31:
        raise ValueError("function_number must be between 0 and 31")
    address_msb = (address >> 8) & 0x3F
    if address >= 128:
        address_msb |= 0xC0
    function_state = (0x40 if enabled else 0x00) | int(function_number)
    return encode_xbus(0xE4, LAN_X_SET_LOCO_FUNCTION, address_msb, address & 0xFF, function_state)


def build_set_turnout(
    function_address: int,
    *,
    active: bool = True,
    output: int = 0,
    queue: bool = True,
) -> bytes:
    """Build LAN_X_SET_TURNOUT (0x40/0x53)."""

    if not 0 <= function_address <= 0xFFFF:
        raise ValueError("function_address must fit 16 bits")
    if output not in (0, 1):
        raise ValueError("output must be 0 or 1")
    # 10Q0A00P: Q is bit 5, A is bit 3, and P is bit 0.
    command = 0x80 | (0x20 if queue else 0) | (0x08 if active else 0) | output
    return encode_xbus(0x53, (function_address >> 8) & 0xFF, function_address & 0xFF, command)


def build_set_track_power(enabled: bool) -> bytes:
    """Build the documented Z21 X-BUS track-power command."""

    return encode_xbus(0x21, LAN_X_SET_TRACK_POWER_ON if enabled else LAN_X_SET_TRACK_POWER_OFF)


def _cv_address(cv: int) -> tuple[int, int]:
    """Convert the user-facing CV number (CV1..CV1024) to Z21's zero-based address."""

    try:
        cv = int(cv)
    except (TypeError, ValueError) as exc:
        raise ValueError("CV must be an integer") from exc
    if not 1 <= cv <= 1024:
        raise ValueError("CV must be between 1 and 1024")
    address = cv - 1
    return (address >> 8) & 0xFF, address & 0xFF


def build_cv_read(cv: int) -> bytes:
    """Build direct-mode CV read (programming track)."""

    high, low = _cv_address(cv)
    return encode_xbus(LAN_X_CV_READ, 0x11, high, low)


def build_cv_write(cv: int, value: int) -> bytes:
    """Build direct-mode CV byte write (programming track)."""

    high, low = _cv_address(cv)
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CV value must be an integer") from exc
    if not 0 <= value <= 255:
        raise ValueError("CV value must be between 0 and 255")
    return encode_xbus(LAN_X_CV_WRITE, 0x12, high, low, value)


def build_cv_pom_read(address: int, cv: int) -> bytes:
    """Build a RailCom POM CV read for a locomotive address."""

    address = _validate_loco_address(address)
    high, low = _cv_address(cv)
    return encode_xbus(LAN_X_CV_POM, 0x30, (address >> 8) & 0x3F, address & 0xFF, 0xE4 | (high & 0x03), low, 0)


def build_cv_pom_write(address: int, cv: int, value: int) -> bytes:
    """Build a POM CV byte write for a locomotive address."""

    address = _validate_loco_address(address)
    high, low = _cv_address(cv)
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CV value must be an integer") from exc
    if not 0 <= value <= 255:
        raise ValueError("CV value must be between 0 and 255")
    return encode_xbus(LAN_X_CV_POM, 0x30, (address >> 8) & 0x3F, address & 0xFF, 0xEC | (high & 0x03), low, value)


def build_rbus_get_data(group_index: int) -> bytes:
    """Build a LAN_RMBUS_GETDATA request for one ten-module group."""

    if not 0 <= int(group_index) <= 255:
        raise ValueError("group_index must fit one byte")
    return encode_dataset(LAN_RMBUS_GETDATA, bytes((int(group_index),)))


def decode_rbus_feedback(value: bytes | Z21Dataset) -> RBusFeedback:
    """Decode a LAN_RMBUS_DATACHANGED response into active module inputs."""

    dataset = decode_dataset(value) if isinstance(value, (bytes, bytearray)) else value
    if dataset.header != LAN_RMBUS_DATACHANGED:
        raise ValueError("dataset is not an R-BUS feedback response")
    if len(dataset.data) != 11:
        raise ValueError("R-BUS feedback response must contain group index plus ten bytes")
    group_index = dataset.data[0]
    bitmap = bytes(dataset.data[1:])
    active: list[tuple[int, int]] = []
    for module_offset, byte_value in enumerate(bitmap):
        module_address = group_index * 10 + module_offset + 1
        for input_offset in range(8):
            if byte_value & (1 << input_offset):
                active.append((module_address, input_offset + 1))
    return RBusFeedback(group_index, bitmap, tuple(active))


def _validate_transport_dataset(dataset: Z21Dataset, *, allow_legacy_version_marker: bool = False) -> None:
    """Validate payload rules that are common to packets crossing the UDP boundary."""

    if dataset.header == LAN_X_HEADER:
        if allow_legacy_version_marker and dataset.data == bytes((LAN_X_GET_VERSION_REPLY, 0x01)):
            # Keep compatibility with the short version marker used by older local fakes.
            return
        if len(dataset.data) < 2:
            raise ValueError("X-BUS dataset must contain a command and checksum")
        expected = xbus_checksum(dataset.data[:-1])
        if dataset.data[-1] != expected:
            raise ValueError("X-BUS checksum mismatch")
    elif dataset.header == LAN_RMBUS_DATACHANGED and len(dataset.data) != 11:
        raise ValueError("R-BUS feedback response must contain group index plus ten bytes")


def _decode_transport_payload(
    packet: bytes,
    *,
    allow_legacy_version_marker: bool = False,
) -> tuple[Z21Dataset, ...]:
    """Decode and validate one UDP payload without accepting oversized LAN packets."""

    try:
        packet = bytes(packet)
    except (TypeError, ValueError) as exc:
        raise ValueError("packet must be bytes-like") from exc
    if len(packet) > Z21_MAX_UDP_PAYLOAD:
        raise ValueError(f"UDP payload exceeds the {Z21_MAX_UDP_PAYLOAD}-byte Ethernet-MTU limit")
    datasets = tuple(iter_datasets(packet))
    for dataset in datasets:
        _validate_transport_dataset(dataset, allow_legacy_version_marker=allow_legacy_version_marker)
    return datasets


def _is_version_response(datasets: tuple[Z21Dataset, ...]) -> bool:
    """Return whether a payload contains the documented X-BUS version reply."""

    for dataset in datasets:
        if dataset.header != LAN_X_HEADER:
            continue
        if dataset.data == bytes((LAN_X_GET_VERSION_REPLY, 0x01)):
            # Backwards-compatible support for the short marker accepted historically.
            return True
        if (
            len(dataset.data) == 5
            and dataset.data[:2] == bytes((LAN_X_GET_VERSION_REPLY, LAN_X_GET_VERSION))
            and dataset.data[3] in Z21_COMMAND_STATION_IDS
        ):
            return True
    return False


class Z21LanTransport:
    """Opt-in UDP adapter that stays disconnected until explicitly checked.

    Constructing this class performs no socket operation.  Calling
    :meth:`open` only allocates a local UDP socket; the first network packet is
    sent by :meth:`check_connection`.  Command methods refuse to send until a
    successful check, which prevents accidental hardware writes while offline.
    """

    def __init__(
        self,
        host: str = "192.168.0.111",
        *,
        port: int = Z21_PORT,
        timeout: float = 1.0,
        connection_attempts: int = 3,
        socket_factory: Callable[[], DatagramSocket] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not host:
            raise ValueError("host is required")
        if not 0 < port <= 0xFFFF:
            raise ValueError("port must be a valid UDP port")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if type(connection_attempts) is not int or connection_attempts < 1:
            raise ValueError("connection_attempts must be a positive integer")
        self.host = host
        self.port = port
        self.timeout = float(timeout)
        self.connection_attempts = connection_attempts
        self._socket_factory = socket_factory or self._default_socket
        self._clock = clock
        self._socket: DatagramSocket | None = None
        self._local_endpoint = ""
        self._last_response_hex = ""
        self._last_response_source = ""
        self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint)

    @property
    def endpoint(self) -> str:
        """Return the configured endpoint without performing I/O."""

        return f"{self.host}:{self.port}"

    def connection_status(self) -> ConnectionStatus:
        """Return the cached status."""

        return self._status

    def open(self) -> ConnectionStatus:
        """Allocate a UDP socket without probing or sending to the Z21."""

        if self._socket is not None:
            return self._status
        try:
            self._socket = self._socket_factory()
            self._socket.settimeout(self.timeout)
            # A connected UDP socket still uses datagrams, but asks Windows
            # to select and retain the route/interface for this endpoint.
            # This is important on laptops with multiple adapters (Wi-Fi,
            # Ethernet, VPN, and virtual switches), and also filters replies
            # to the configured command station instead of an arbitrary local
            # datagram source.
            connect_socket = getattr(self._socket, "connect", None)
            if callable(connect_socket):
                connect_socket((self.host, self.port))
            get_socket_name = getattr(self._socket, "getsockname", None)
            if callable(get_socket_name):
                try:
                    local = get_socket_name()
                    self._local_endpoint = f"{local[0]}:{local[1]}"
                except (OSError, TypeError, ValueError, IndexError):
                    self._local_endpoint = ""
            self._status = ConnectionStatus(ConnectionState.CONNECTING, self.endpoint, checked_at=self._clock())
        except (OSError, TypeError, ValueError) as exc:
            socket_obj, self._socket = self._socket, None
            if socket_obj is not None:
                try:
                    socket_obj.close()
                except OSError:
                    pass
            self._socket = None
            self._local_endpoint = ""
            self._status = ConnectionStatus(ConnectionState.ERROR, self.endpoint, str(exc), self._clock())
        return self._status

    connect = open

    def close(self) -> None:
        """Close the local socket and return to a disconnected state."""

        socket_obj, self._socket = self._socket, None
        self._local_endpoint = ""
        if socket_obj is not None:
            try:
                if self._status.connected:
                    socket_obj.sendto(build_logoff(), (self.host, self.port))
            except OSError:
                pass
            finally:
                try:
                    socket_obj.close()
                except OSError:
                    pass
        self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, checked_at=self._clock())

    disconnect = close

    def check_connection(self) -> ConnectionStatus:
        """Send a bounded version request and cache the result."""

        if self._socket is None:
            self._status = ConnectionStatus(
                ConnectionState.DISCONNECTED,
                self.endpoint,
                "transport is not open",
                self._clock(),
            )
            return self._status
        try:
            request = build_get_version()
            self._last_response_hex = ""
            self._last_response_source = ""
            for attempt in range(1, self.connection_attempts + 1):
                sent = self._socket.sendto(request, (self.host, self.port))
                if sent != len(request):
                    raise OSError("short UDP send while checking the Z21 connection")
                try:
                    datasets = self._receive_until(_is_version_response, allow_legacy_version_marker=True)
                except TimeoutError:
                    if attempt == self.connection_attempts:
                        received = (
                            f"; last UDP packet from {self._last_response_source}: {self._last_response_hex}"
                            if self._last_response_hex else "; no UDP datagram was received"
                        )
                        local = f" from local {self._local_endpoint}" if self._local_endpoint else ""
                        raise TimeoutError(
                            f"Z21 version reply timeout after {self.connection_attempts} attempts; "
                            f"sent {request.hex(' ')}{local}{received}"
                        )
                    continue
                if not _is_version_response(datasets):
                    raise ValueError("unexpected Z21 version response")
                self._status = ConnectionStatus(
                    ConnectionState.CONNECTED,
                    self.endpoint,
                    f"Z21 version reply received on attempt {attempt}",
                    self._clock(),
                )
                break
        except (OSError, TypeError, ValueError) as exc:
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, str(exc), self._clock())
        return self._status

    def send_dataset(self, packet: bytes, *, command: str = "send_dataset") -> CommandResult:
        """Send a packet only after an explicit successful connection check."""

        if not self._status.connected or self._socket is None:
            return CommandResult(False, command, f"Z21 is not connected at {self.endpoint}: {self._status.detail or self._status.state.value}")
        try:
            packet = bytes(packet)
            _decode_transport_payload(packet)
        except (TypeError, ValueError) as exc:
            return CommandResult(False, command, str(exc))
        try:
            sent = self._socket.sendto(packet, (self.host, self.port))
            if sent != len(packet):
                raise OSError("short UDP send")
        except OSError as exc:
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, str(exc), self._clock())
            return CommandResult(False, command, str(exc))
        return CommandResult(True, command, "packet sent", bytes(packet))

    def request_datasets(
        self,
        packet: bytes,
        *,
        expected_header: int | None = None,
        command: str = "request_dataset",
        keep_connection_on_timeout: bool = False,
    ) -> tuple[CommandResult, tuple[Z21Dataset, ...]]:
        """Send one request and decode the combined response datasets."""

        if not self._status.connected or self._socket is None:
            return CommandResult(False, command, f"Z21 is not connected at {self.endpoint}: {self._status.detail or self._status.state.value}"), ()
        try:
            packet = bytes(packet)
            _decode_transport_payload(packet)
        except (TypeError, ValueError) as exc:
            return CommandResult(False, command, str(exc)), ()
        try:
            sent = self._socket.sendto(packet, (self.host, self.port))
            if sent != len(packet):
                raise OSError("short UDP send")
            datasets = self._receive_until(
                lambda received: expected_header is None
                or any(dataset.header == expected_header for dataset in received),
            )
        except TimeoutError as exc:
            if keep_connection_on_timeout:
                return CommandResult(False, command, str(exc)), ()
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, str(exc), self._clock())
            return CommandResult(False, command, str(exc)), ()
        except (OSError, TypeError, ValueError) as exc:
            self._status = ConnectionStatus(ConnectionState.DISCONNECTED, self.endpoint, str(exc), self._clock())
            return CommandResult(False, command, str(exc)), ()
        response_payload = b"".join(dataset.encode() for dataset in datasets)
        return CommandResult(True, command, "response received", response_payload), datasets

    def _receive_until(
        self,
        matches: Callable[[tuple[Z21Dataset, ...]], bool],
        *,
        allow_legacy_version_marker: bool = False,
    ) -> tuple[Z21Dataset, ...]:
        """Receive valid datasets until the requested response arrives or the budget expires."""

        if self._socket is None:
            raise OSError("Z21 socket is not open")
        deadline = self._clock() + self.timeout
        for _ in range(Z21_MAX_RESPONSE_DATAGRAMS):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for the Z21 response")
            self._socket.settimeout(max(0.001, min(self.timeout, remaining)))
            response, source = self._socket.recvfrom(Z21_MAX_UDP_PAYLOAD)
            self._last_response_hex = response.hex(" ")
            try:
                self._last_response_source = f"{source[0]}:{source[1]}"
            except (IndexError, TypeError):
                self._last_response_source = str(source)
            datasets = _decode_transport_payload(
                response,
                allow_legacy_version_marker=allow_legacy_version_marker,
            )
            if matches(datasets):
                return datasets
        raise TimeoutError("too many unrelated Z21 datagrams")

    @staticmethod
    def _cv_reply(datasets: tuple[Z21Dataset, ...], *, command: str) -> tuple[CommandResult, int | None]:
        for dataset in datasets:
            data = dataset.data
            if dataset.header != LAN_X_HEADER or not data:
                continue
            if data[:2] == bytes((LAN_X_CV_RESULT, 0x14)) and len(data) >= 6:
                return CommandResult(True, command, "CV programming acknowledged", data), int(data[4])
            if data[:2] == bytes((LAN_X_CV_NACK, 0x12)):
                return CommandResult(False, command, "Z21 reported a programming-track short circuit", data), None
            if data[:2] == bytes((LAN_X_CV_NACK, 0x13)):
                return CommandResult(False, command, "decoder did not acknowledge the CV operation", data), None
        return CommandResult(False, command, "Z21 returned no CV result", b""), None

    def read_cv(self, cv: int) -> tuple[CommandResult, int | None]:
        """Read a CV in direct service mode on the programming track."""

        try:
            packet = build_cv_read(cv)
        except ValueError as exc:
            return CommandResult(False, "read_cv", str(exc)), None
        result, datasets = self.request_datasets(packet, expected_header=LAN_X_HEADER, command="read_cv")
        if not result.accepted:
            return result, None
        return self._cv_reply(datasets, command="read_cv")

    def write_cv(self, cv: int, value: int) -> CommandResult:
        """Write a CV in direct service mode on the programming track."""

        try:
            packet = build_cv_write(cv, value)
        except ValueError as exc:
            return CommandResult(False, "write_cv", str(exc))
        result, datasets = self.request_datasets(packet, expected_header=LAN_X_HEADER, command="write_cv")
        if not result.accepted:
            return result
        return self._cv_reply(datasets, command="write_cv")[0]

    def write_cv_pom(self, address: int, cv: int, value: int) -> CommandResult:
        """Write a locomotive CV on the main track (POM)."""

        try:
            packet = build_cv_pom_write(address, cv, value)
        except ValueError as exc:
            return CommandResult(False, "write_cv_pom", str(exc))
        return self.send_dataset(packet, command="write_cv_pom")

    def read_cv_pom(self, address: int, cv: int) -> tuple[CommandResult, int | None]:
        """Read a locomotive CV on the main track via RailCom."""

        try:
            packet = build_cv_pom_read(address, cv)
        except ValueError as exc:
            return CommandResult(False, "read_cv_pom", str(exc)), None
        result, datasets = self.request_datasets(packet, expected_header=LAN_X_HEADER, command="read_cv_pom")
        if not result.accepted:
            return result, None
        return self._cv_reply(datasets, command="read_cv_pom")

    def probe_railcom(self, address: int) -> tuple[CommandResult, bool]:
        """Poll RailCom for a saved address without disconnecting on no reply."""

        try:
            packet = build_railcom_get_data(address)
        except ValueError as exc:
            return CommandResult(False, "probe_railcom", str(exc)), False
        result, datasets = self.request_datasets(
            packet,
            expected_header=LAN_RAILCOM_DATACHANGED,
            command="probe_railcom",
            keep_connection_on_timeout=True,
        )
        if not result.accepted:
            return CommandResult(False, "probe_railcom", "no RailCom response"), False
        expected = int(address)
        for dataset in datasets:
            if dataset.header == LAN_RAILCOM_DATACHANGED and len(dataset.data) >= 2:
                seen = int.from_bytes(dataset.data[:2], "little")
                if seen == expected:
                    return CommandResult(True, "probe_railcom", "RailCom decoder response received", dataset.data), True
        return CommandResult(False, "probe_railcom", "RailCom response did not identify the requested address"), False

    def set_loco_drive(
        self,
        address: int,
        speed: int,
        *,
        forward: bool = True,
        speed_steps: int = 128,
    ) -> CommandResult:
        """Send a validated locomotive drive command when connected."""

        try:
            packet = build_set_loco_drive(address, speed, forward=forward, speed_steps=speed_steps)
        except ValueError as exc:
            return CommandResult(False, "set_loco_drive", str(exc))
        return self.send_dataset(packet, command="set_loco_drive")

    def set_loco_function(self, address: int, function_number: int, *, enabled: bool) -> CommandResult:
        """Send a DCC decoder function command when connected."""

        try:
            packet = build_set_loco_function(address, function_number, enabled=enabled)
        except ValueError as exc:
            return CommandResult(False, "set_loco_function", str(exc))
        return self.send_dataset(packet, command="set_loco_function")

    def set_turnout(
        self,
        function_address: int,
        *,
        active: bool = True,
        output: int = 0,
        queue: bool = True,
    ) -> CommandResult:
        """Send a validated turnout command when connected."""

        try:
            packet = build_set_turnout(
                function_address,
                active=active,
                output=output,
                queue=queue,
            )
        except ValueError as exc:
            return CommandResult(False, "set_turnout", str(exc))
        return self.send_dataset(packet, command="set_turnout")

    @staticmethod
    def _default_socket() -> DatagramSocket:
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
