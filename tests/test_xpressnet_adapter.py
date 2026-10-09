"""LI-USB wire replies, command acknowledgment and safe failure behavior."""

from __future__ import annotations

from unittest.mock import patch
import unittest

from backend.infrastructure.xpressnet import XpressNetSerialTransport, XpressNetTrackSystem, decoder_bytes, encode_frame
from backend.infrastructure.interfaces import ConnectionState


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.input = bytearray()
        self.powered = False
        self.respond = True
        self.corrupt = False
        self.reject = False
        self.closed = False
        self.groups = {32: 2, 33: 4, 34: 8, 35: 1, 40: 128}
        self.contacts = {0: 1, 1: 8}
        self.short_write = False

    def write(self, packet):
        self.writes.append(packet)
        if self.short_write:
            return len(packet) - 1
        if not self.respond:
            return len(packet)
        message = packet[2:-1]
        if self.reject:
            reply = bytes((1, 8))
        elif message == bytes((33, 36)):
            reply = bytes((98, 34, 0 if self.powered else 2))
        elif message in (bytes((33, 129)), bytes((33, 128))):
            self.powered = message[1] == 129
            reply = bytes((97, int(self.powered)))
        elif message[:2] == bytes((227, 0)):
            reply = bytes((228, 4, 128, self.groups[32], self.groups[33] | (self.groups[34] << 4)))
        elif message[:2] == bytes((227, 9)):
            reply = bytes((227, 82, self.groups[35], self.groups[40]))
        elif message[0] == 66:
            nibble = message[2] & 1
            reply = bytes((66, message[1], 64 | (nibble << 4) | self.contacts[nibble]))
        else:
            if message[0] == 228 and message[1] in self.groups:
                self.groups[message[1]] = message[4]
            reply = bytes((1, 4))
        encoded = encode_frame(reply)
        if self.corrupt:
            encoded = encoded[:-1] + bytes((encoded[-1] ^ 1,))
        self.input.extend(encoded)
        return len(packet)

    def read(self, size):
        value = bytes(self.input[:size])
        del self.input[:size]
        return value

    def close(self):
        self.closed = True


class XpressNetAdapterTests(unittest.TestCase):
    def setUp(self):
        self.serial = FakeSerial()
        self.track = XpressNetTrackSystem(serial_port="COM7", serial_factory=lambda **kwargs: self.serial)
        self.addCleanup(self.track.close)
        self.track.register_train("engine", 1234)

    def enable(self):
        self.assertTrue(self.track.check_connection().connected)
        self.assertTrue(self.track.set_power(True).accepted)

    def test_framing_and_decoder_address_follow_wire_spec(self):
        self.assertEqual(encode_frame(bytes((33, 36))), bytes.fromhex("ff fe 21 24 05"))
        self.assertEqual(decoder_bytes(99), bytes((0, 99)))
        self.assertEqual(decoder_bytes(100), bytes((192, 100)))
        self.assertEqual(decoder_bytes(1234), bytes((196, 210)))
        with self.assertRaises(ValueError):
            encode_frame(bytes((33,)))

    def test_connect_only_polls_without_powering_or_moving_train(self):
        self.assertTrue(self.track.check_connection().connected)
        self.assertEqual(self.serial.writes, [bytes.fromhex("ff fe 21 24 05")])
        self.assertFalse(self.track.get_snapshot().powered)
        self.assertFalse(self.track.set_train_speed("engine", .5).accepted)
        self.assertEqual(len(self.serial.writes), 1)

    def test_explicit_power_and_drive_stop_direction_have_expected_bytes(self):
        self.enable()
        self.assertTrue(self.track.set_train_speed("engine", 1).accepted)
        self.assertEqual(self.serial.writes[-1][2:-1], bytes((228, 19, 196, 210, 255)))
        self.assertFalse(self.track.set_train_direction("engine", forward=False).accepted)
        self.assertTrue(self.track.stop_train("engine").accepted)
        self.assertEqual(self.serial.writes[-1][2:-1], bytes((228, 19, 196, 210, 128)))
        self.assertTrue(self.track.set_train_direction("engine", forward=False).accepted)
        self.assertEqual(self.serial.writes[-1][2:-1], bytes((228, 19, 196, 210, 0)))

    def test_function_changes_preserve_every_other_function_in_group(self):
        self.enable()
        self.assertTrue(self.track.set_train_function("engine", 0, enabled=True).accepted)
        self.assertEqual(self.serial.groups[32], 18)  # existing F2 stays on
        self.assertTrue(self.track.set_train_function("engine", 28, enabled=False).accepted)
        self.assertEqual(self.serial.groups[40], 0)
        self.serial.groups[35] = 129
        self.assertTrue(self.track.set_function_by_address(1234, 14, enabled=True).accepted)
        self.assertEqual(self.serial.groups[35], 131)
        before = len(self.serial.writes)
        self.assertFalse(self.track.set_train_function("engine", 29, enabled=True).accepted)
        self.assertEqual(len(self.serial.writes), before)

    def test_no_station_reply_never_changes_commanded_speed(self):
        self.enable()
        self.serial.respond = False
        result = self.track.set_train_speed("engine", .5)
        self.assertFalse(result.accepted)
        self.assertEqual(self.track.get_effective_speed("engine"), 0)
        self.assertEqual(self.track.connection_status().state, ConnectionState.ERROR)
        self.assertFalse(self.track.get_snapshot().powered)

    def test_bad_checksum_short_write_and_interface_rejection_are_errors(self):
        for attribute in ("corrupt", "short_write", "reject"):
            with self.subTest(attribute=attribute):
                self.serial.corrupt = self.serial.short_write = self.serial.reject = False
                self.assertTrue(self.track.check_connection().connected)
                setattr(self.serial, attribute, True)
                self.assertFalse(self.track.check_connection().connected)
                self.assertEqual(self.track.connection_status().state, ConnectionState.ERROR)

    def test_turnout_activation_is_always_followed_by_release(self):
        self.enable()
        with patch("backend.infrastructure.xpressnet.time.sleep"):
            self.assertTrue(self.track.set_turnout_by_address(6, output=1).accepted)
        self.assertEqual(self.serial.writes[-2][2:-1], bytes((82, 1, 139)))
        self.assertEqual(self.serial.writes[-1][2:-1], bytes((82, 1, 131)))

    def test_feedback_reads_nibbles_and_maps_only_actual_contacts(self):
        self.enable()
        self.track.bind_feedback(7, 1, "B01")
        self.track.bind_feedback(7, 8, "B08")
        self.track.bind_feedback(7, 4, "B04")
        self.assertTrue(all(result.accepted for result in self.track.poll_feedback()))
        self.assertEqual(set(self.track.get_snapshot().occupied_blocks), {"B01", "B08"})
        self.assertTrue(self.track.feedback_healthy)
        self.serial.respond = False
        self.assertFalse(self.track.poll_feedback()[0].accepted)
        self.assertFalse(self.track.feedback_healthy)
        self.assertEqual(set(self.track.get_snapshot().occupied_blocks), {"B01", "B08"})

    def test_power_off_broadcast_during_drive_prevents_acceptance(self):
        self.enable()
        self.serial.input.extend(encode_frame(bytes((97, 0)), broadcast=True))
        self.assertFalse(self.track.set_train_speed("engine", .5).accepted)
        self.assertFalse(self.track.get_snapshot().powered)

    def test_function_group_read_failure_sends_no_function_command(self):
        self.enable()
        self.serial.respond = False
        previous = len(self.serial.writes)
        self.assertFalse(self.track.set_train_function("engine", 0, enabled=True).accepted)
        self.assertEqual(len(self.serial.writes), previous + 1)
        self.assertEqual(self.serial.writes[-1][2:4], bytes((227, 0)))

    def test_invalid_addresses_protocols_and_feedback_are_rejected(self):
        for address in (0, 10000, True):
            with self.assertRaises(ValueError):
                self.track.register_train("other", address)
        with self.assertRaises(ValueError):
            self.track.register_train("other", 1, decoder_protocol="mfx")
        with self.assertRaises(ValueError):
            self.track.bind_feedback(128, 1, "B01")
        self.assertFalse(self.track.read_cv("engine", 1)[0].accepted)

    def test_close_releases_serial_connection(self):
        self.track.close()
        self.assertTrue(self.serial.closed)
        self.assertEqual(self.track.connection_status().state, ConnectionState.DISCONNECTED)

    def test_missing_serial_package_has_actionable_error_without_simulation_fallback(self):
        transport = XpressNetSerialTransport("COM5")
        with patch.dict("sys.modules", {"serial": None}), self.assertRaisesRegex(ValueError, "requires pyserial"):
            transport.open()
        self.assertFalse(transport.connection_status().connected)

    def test_station_stops_polling_interface_broadcast_rejects_pending_drive(self):
        self.enable()
        self.serial.input.extend(encode_frame(bytes((1, 5)), broadcast=True))
        self.assertFalse(self.track.set_train_speed("engine", .5).accepted)
        self.assertFalse(self.track.get_snapshot().powered)


if __name__ == "__main__":
    unittest.main()
