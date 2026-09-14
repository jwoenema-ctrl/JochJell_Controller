from __future__ import annotations

import unittest

from backend.api.server import ControllerApplication
from backend.infrastructure.real_track import Z21TrackSystem
from backend.infrastructure.z21 import LAN_X_HEADER, Z21LanTransport, encode_dataset


class _Z21Socket:
    def __init__(self) -> None:
        self.responses = [encode_dataset(LAN_X_HEADER, b"\x63\x21\x30\x12\x60")]

    def settimeout(self, _value: float | None) -> None:
        return

    def sendto(self, data: bytes, _address: tuple[str, int]) -> int:
        return len(data)

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        return self.responses.pop(0), ("127.0.0.1", 21105)

    def close(self) -> None:
        return


class TrackPowerSafetyTests(unittest.TestCase):
    def test_application_close_powers_down_before_releasing_runtime(self) -> None:
        app = ControllerApplication.sample()
        track = app.runtime.track

        app.close()

        self.assertFalse(track.get_snapshot().powered)
        app.close()

    def test_power_off_stops_registered_trains_before_power_change(self) -> None:
        app = ControllerApplication.sample()
        try:
            app.command({"type": "speed", "train_id": "t1", "speed": 70})
            result = app.command({"type": "track_power", "enabled": False})
            self.assertFalse(result["track_power"])
            self.assertTrue(all(item["speed"] == 0 for item in result["trains"]))
            self.assertTrue(all(item.target_speed == 0 for item in app.runtime.track.get_snapshot().trains))
        finally:
            app.close()

    def test_rejected_power_command_does_not_mutate_application_state(self) -> None:
        app = ControllerApplication.sample()
        try:
            original_set_power = app.runtime.track.set_power
            app.runtime.track.set_power = lambda enabled: type("Result", (), {
                "accepted": False,
                "detail": "hardware refused power change",
            })()
            with self.assertRaisesRegex(ValueError, "hardware refused"):
                app.command({"type": "track_power", "enabled": False})
            self.assertTrue(app.track_power)
        finally:
            app.runtime.track.set_power = original_set_power
            app.close()

    def test_small_nonzero_real_speed_does_not_emit_reserved_emergency_value(self) -> None:
        socket = _Z21Socket()
        transport = Z21LanTransport(socket_factory=lambda: socket)
        transport.open()
        self.assertTrue(transport.check_connection().connected)
        track = Z21TrackSystem(transport)
        track.register_train("train-1", 3)
        result = track.set_train_speed("train-1", 1 / 126)
        self.assertTrue(result.accepted)


if __name__ == "__main__":
    unittest.main()
