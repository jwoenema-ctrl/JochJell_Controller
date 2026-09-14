"""Focused tests for the bounded Z21 LAN transport boundary."""

from __future__ import annotations

import unittest

from backend.infrastructure.z21 import (
    LAN_RMBUS_DATACHANGED,
    LAN_X_HEADER,
    Z21_MAX_UDP_PAYLOAD,
    Z21LanTransport,
    build_get_version,
    build_rbus_get_data,
    build_set_track_power,
    decode_dataset,
    encode_dataset,
    encode_xbus,
    iter_datasets,
)


class FakeDatagramSocket:
    """Small deterministic UDP double that exposes all transport interactions."""

    def __init__(self, responses: list[bytes | BaseException] | None = None, *, send_returns: list[int] | None = None) -> None:
        self.responses = list(responses or [])
        self.send_returns = list(send_returns or [])
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.timeouts: list[float | None] = []
        self.closed = False

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        return self.send_returns.pop(0) if self.send_returns else len(data)

    def recvfrom(self, _buffer_size: int) -> tuple[bytes, tuple[str, int]]:
        if not self.responses:
            raise TimeoutError("test socket timeout")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response, ("127.0.0.1", 21105)

    def close(self) -> None:
        self.closed = True


def version_reply() -> bytes:
    """The five-byte X-BUS data field specified for LAN_X_GET_VERSION."""

    return encode_dataset(LAN_X_HEADER, b"\x63\x21\x30\x12\x60")


def z21start_version_reply() -> bytes:
    """Reply observed from a z21start running the user's firmware."""

    return encode_dataset(LAN_X_HEADER, b"\x63\x21\x40\x13\x11")


def power_broadcast() -> bytes:
    return encode_xbus(0x61, 0x00)


def rbus_reply(group_index: int = 0) -> bytes:
    return encode_dataset(LAN_RMBUS_DATACHANGED, bytes((group_index, 0x01)) + bytes(9))


def connected_transport(socket: FakeDatagramSocket) -> Z21LanTransport:
    transport = Z21LanTransport(socket_factory=lambda: socket)
    transport.open()
    assert transport.check_connection().connected
    return transport


class Z21TransportTests(unittest.TestCase):
    def test_disconnected_commands_and_ui_preserve_latest_transport_failure(self):
        from backend.api.server import ControllerApplication
        from unittest.mock import Mock

        socket = FakeDatagramSocket()
        transport = Z21LanTransport(socket_factory=lambda: socket)
        transport.open()
        status = transport.check_connection()
        result = transport.send_dataset(build_set_track_power(False))
        self.assertIn(status.detail, result.detail)
        self.assertIn(transport.endpoint, result.detail)
        request, _ = transport.request_datasets(build_rbus_get_data(0))
        self.assertIn(status.detail, request.detail)

        app = ControllerApplication.sample()
        original_track = app.runtime.track
        try:
            app.z21_host = transport.host
            app.simulation_mode = False
            app.runtime.track = Mock(wraps=original_track)
            app.runtime.track.connection_status = Mock(return_value=status)
            payload = app.state()["connection"]
            self.assertFalse(payload["connected"])
            self.assertEqual(payload["detail"], status.detail)
            self.assertEqual(payload["label"], "Z21 disconnected")
        finally:
            app.runtime.track = original_track
            app.close()

    def test_documented_framing_and_combined_datasets_round_trip(self) -> None:
        first = encode_dataset(0x0010, b"abc")
        second = encode_xbus(0x61, 0x01)

        self.assertEqual(decode_dataset(first).data, b"abc")
        self.assertEqual(tuple(iter_datasets(first + second)), (decode_dataset(first), decode_dataset(second)))
        self.assertEqual(build_get_version(), b"\x07\x00\x40\x00\x21\x21\x00")

    def test_framing_rejects_empty_truncated_and_mismatched_payloads(self) -> None:
        with self.assertRaises(ValueError):
            tuple(iter_datasets(b""))
        with self.assertRaises(ValueError):
            decode_dataset(b"\x04\x00\x10")
        with self.assertRaises(ValueError):
            decode_dataset(b"\x08\x00\x10\x00abc")

    def test_connection_skips_async_broadcast_before_documented_version_reply(self) -> None:
        socket = FakeDatagramSocket([power_broadcast(), version_reply()])
        transport = Z21LanTransport(socket_factory=lambda: socket)

        transport.open()
        status = transport.check_connection()

        self.assertTrue(status.connected)
        self.assertEqual(socket.sent[0][0], build_get_version())
        self.assertEqual(len(socket.responses), 0)

    def test_connection_retries_a_late_v143_version_reply(self) -> None:
        socket = FakeDatagramSocket([TimeoutError("first reply was late"), version_reply()])
        transport = Z21LanTransport(socket_factory=lambda: socket)

        transport.open()
        status = transport.check_connection()

        self.assertTrue(status.connected)
        self.assertEqual(len(socket.sent), 2)
        self.assertIn("attempt 2", status.detail)

    def test_connection_accepts_z21start_command_station_id_13(self) -> None:
        socket = FakeDatagramSocket([z21start_version_reply()])
        transport = Z21LanTransport(socket_factory=lambda: socket)

        transport.open()
        status = transport.check_connection()

        self.assertTrue(status.connected)
        self.assertIn("attempt 1", status.detail)

    def test_connection_reports_exhausted_retry_budget(self) -> None:
        socket = FakeDatagramSocket()
        transport = Z21LanTransport(socket_factory=lambda: socket)

        transport.open()
        status = transport.check_connection()

        self.assertFalse(status.connected)
        self.assertEqual(len(socket.sent), 3)
        self.assertIn("after 3 attempts", status.detail)
        self.assertIn("sent 07 00 40 00 21 21 00", status.detail)
        self.assertIn("no UDP datagram was received", status.detail)

    def test_connection_rejects_bad_xbus_checksum(self) -> None:
        bad_reply = encode_dataset(LAN_X_HEADER, b"\x63\x21\x30\x12\x61")
        socket = FakeDatagramSocket([bad_reply])
        transport = Z21LanTransport(socket_factory=lambda: socket)

        transport.open()
        status = transport.check_connection()

        self.assertFalse(status.connected)
        self.assertIn("checksum", status.detail)

    def test_connection_rejects_a_non_z21_command_station_id(self) -> None:
        non_z21_reply = encode_dataset(LAN_X_HEADER, b"\x63\x21\x30\x99\xEB")
        socket = FakeDatagramSocket([non_z21_reply])
        transport = Z21LanTransport(socket_factory=lambda: socket)

        transport.open()
        status = transport.check_connection()

        self.assertFalse(status.connected)
        self.assertIn("timeout", status.detail)
        self.assertIn("last UDP packet from 127.0.0.1:21105", status.detail)
        self.assertIn("09 00 40 00 63 21 30 99 eb", status.detail.lower())

    def test_request_waits_for_expected_header_and_returns_validated_response(self) -> None:
        socket = FakeDatagramSocket([version_reply(), power_broadcast(), rbus_reply()])
        transport = connected_transport(socket)

        result, datasets = transport.request_datasets(
            build_rbus_get_data(0),
            expected_header=LAN_RMBUS_DATACHANGED,
            command="poll_feedback",
        )

        self.assertTrue(result.accepted)
        self.assertEqual(datasets[0].header, LAN_RMBUS_DATACHANGED)
        self.assertEqual(result.payload, rbus_reply())

    def test_malformed_rbus_response_is_a_safe_transport_failure(self) -> None:
        malformed = encode_dataset(LAN_RMBUS_DATACHANGED, b"\x00")
        socket = FakeDatagramSocket([version_reply(), malformed])
        transport = connected_transport(socket)

        result, datasets = transport.request_datasets(
            build_rbus_get_data(0),
            expected_header=LAN_RMBUS_DATACHANGED,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(datasets, ())
        self.assertFalse(transport.connection_status().connected)
        self.assertIn("R-BUS", result.detail)

    def test_malformed_or_oversized_outbound_packets_are_not_sent(self) -> None:
        socket = FakeDatagramSocket([version_reply()])
        transport = connected_transport(socket)
        sent_after_check = len(socket.sent)

        malformed = encode_dataset(LAN_X_HEADER, b"\x21\x80\x00")
        malformed_result = transport.send_dataset(malformed)
        oversized = encode_dataset(0x0010, b"x" * (Z21_MAX_UDP_PAYLOAD - 3))
        oversized_result = transport.send_dataset(oversized)

        self.assertFalse(malformed_result.accepted)
        self.assertFalse(oversized_result.accepted)
        self.assertTrue(transport.connection_status().connected)
        self.assertEqual(len(socket.sent), sent_after_check)

    def test_short_udp_send_disconnects_before_reporting_failure(self) -> None:
        version_packet = version_reply()
        socket = FakeDatagramSocket([version_packet], send_returns=[len(build_get_version()), 0])
        transport = connected_transport(socket)

        result = transport.send_dataset(build_set_track_power(False), command="set_power")

        self.assertFalse(result.accepted)
        self.assertIn("short UDP send", result.detail)
        self.assertFalse(transport.connection_status().connected)

    def test_open_closes_socket_when_timeout_setup_fails(self) -> None:
        class FailingTimeoutSocket(FakeDatagramSocket):
            def settimeout(self, value: float | None) -> None:
                super().settimeout(value)
                raise OSError("cannot set timeout")

        socket = FailingTimeoutSocket()
        transport = Z21LanTransport(socket_factory=lambda: socket)

        status = transport.open()

        self.assertEqual(status.state.value, "error")
        self.assertTrue(socket.closed)
        self.assertEqual(transport.connection_status(), status)

    def test_close_swallows_logoff_and_socket_close_errors(self) -> None:
        class FailingCloseSocket(FakeDatagramSocket):
            def sendto(self, data: bytes, address: tuple[str, int]) -> int:
                if data == encode_dataset(0x0030):
                    raise OSError("logoff failed")
                return super().sendto(data, address)

            def close(self) -> None:
                self.closed = True
                raise OSError("close failed")

        socket = FailingCloseSocket([version_reply()])
        transport = connected_transport(socket)

        transport.close()

        self.assertFalse(transport.connection_status().connected)
        self.assertTrue(socket.closed)

    def test_reserved_emergency_stop_speed_is_not_emitted_as_normal_drive(self) -> None:
        from backend.infrastructure.z21 import build_set_loco_drive

        with self.assertRaisesRegex(ValueError, "reserved"):
            build_set_loco_drive(3, 1)
        with self.assertRaises(ValueError):
            build_set_loco_drive(0, 0)


if __name__ == "__main__":
    unittest.main()
