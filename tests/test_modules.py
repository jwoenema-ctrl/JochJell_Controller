"""Focused coverage for the modular railway building blocks."""

from __future__ import annotations

import unittest

from backend.core import Block, LayoutGraphBuilder, LayoutSnapshot, Turnout, TurnoutPosition
from backend.runtime import ControllerRuntime
from backend.infrastructure.simulation import SimulatedTrackSystem
from backend.infrastructure.train_database import SQLiteTrainDatabase, TrainModel
from backend.infrastructure.real_track import Z21TrackSystem
from backend.infrastructure.z21 import LAN_RMBUS_DATACHANGED, LAN_X_HEADER, Z21LanTransport, build_rbus_get_data, build_set_track_power, decode_dataset, decode_rbus_feedback, encode_dataset
from backend.services.avoidance import AvoidanceDetector
from backend.services.interlocking import MovementAuthorityService
from backend.services.scheduler import ScheduleStop, TimetableService
from backend.services.routing import a_star_route


class ModuleTests(unittest.TestCase):
    def test_a_star_and_layout_graph_are_deterministic(self) -> None:
        self.assertEqual(a_star_route("A", "C", {"A": ("B",), "B": ("C",), "C": ()}), ("A", "B", "C"))
        self.assertEqual(LayoutGraphBuilder().build(LayoutSnapshot.empty()).nodes, ())

    def test_simulator_moves_and_reports_occupancy(self) -> None:
        track = SimulatedTrackSystem(tick_seconds=1, acceleration=1, blocks=["B01", "B02"])
        self.assertTrue(track.add_train("T1", "B01", route=("B01", "B02"), speed=1).accepted)
        track.tick()
        self.assertEqual(track.get_snapshot().occupied_blocks, {"B02": ("T1",)})

    def test_simulator_holds_at_an_occupied_block_boundary(self) -> None:
        track = SimulatedTrackSystem(tick_seconds=1, acceleration=1, blocks=["B01", "B02"])
        track.add_train("T1", "B02", route=("B02",), speed=0)
        track.add_train("T2", "B01", route=("B01", "B02"), speed=1)
        track.tick()
        snapshot = track.get_snapshot()
        self.assertEqual(snapshot.occupied_blocks, {"B01": ("T2",), "B02": ("T1",)})
        self.assertEqual(next(item for item in snapshot.trains if item.train_id == "T2").target_speed, 0)

    def test_simulator_remembers_decoder_function_states(self) -> None:
        track = SimulatedTrackSystem(blocks=["B01"])
        track.add_train("T1", "B01")
        self.assertTrue(track.set_train_function("T1", 2, enabled=True).accepted)
        self.assertEqual(track.get_train_functions("T1"), {2: True})
        self.assertTrue(track.set_train_function("T1", 2, enabled=False).accepted)
        self.assertEqual(track.get_train_functions("T1"), {2: False})

    def test_database_and_safety_services(self) -> None:
        with SQLiteTrainDatabase() as database:
            database.upsert(TrainModel("T1", "Test locomotive", decoder_address=3))
            self.assertEqual(database.get("T1").decoder_address, 3)
        conflicts = AvoidanceDetector().detect({"B01": ("T1", "T2")})
        self.assertEqual(conflicts[0].kind, "multiple_trains_in_block")

    def test_interlocking_serializes_turnout_claims_and_releases_stale_locks(self) -> None:
        snapshot = LayoutSnapshot(
            blocks=(
                Block("A", neighbor_ids=("B",)),
                Block("B", neighbor_ids=("A", "C", "D")),
                Block("C"),
                Block("D"),
            ),
            turnouts=(Turnout("T", "Yard turnout", "B", "C", "D", TurnoutPosition.STRAIGHT),),
        )
        service = MovementAuthorityService(LayoutGraphBuilder().build(snapshot))
        first = service.evaluate({"T1": ("A", "B", "C"), "T2": ("B", "C")})
        self.assertEqual(first["T1"].locked_turnouts, ("T",))
        self.assertTrue(first["T2"].blocked)
        self.assertEqual(first["T2"].reason, "turnout_locked")
        self.assertEqual(service.locks, {"T": "T1"})
        released = service.evaluate({"T2": ("B", "C")})
        self.assertFalse(released["T2"].blocked)
        self.assertEqual(service.locks, {"T": "T2"})

    def test_schedule_simulation_and_z21_framing(self) -> None:
        timetable = TimetableService()
        timetable.add_stop(ScheduleStop("S1", "T1", "ST01", 1, 2))
        timetable.start()
        self.assertEqual(len(timetable.advance(2)), 2)
        packet = encode_dataset(LAN_X_HEADER, b"abc")
        self.assertEqual(decode_dataset(packet).data, b"abc")

    def test_runtime_composes_simulation_and_dispatcher(self) -> None:
        runtime = ControllerRuntime.create()
        try:
            runtime.add_train("T1", "B01", route=("B01", "B02"))
            cycle = runtime.tick()
            self.assertEqual(cycle.snapshot.tick, 1)
            self.assertTrue(runtime.connection.check().status.connected)
            self.assertEqual(runtime.layout_repository.list(), ())
        finally:
            runtime.close()

    def test_real_track_binds_train_ids_to_dcc_addresses(self) -> None:
        class FakeDatagramSocket:
            def __init__(self) -> None:
                self.sent = []

            def settimeout(self, _value: float) -> None:
                return None

            def sendto(self, data: bytes, address: tuple[str, int]) -> int:
                self.sent.append((data, address))
                return len(data)

            def recvfrom(self, _buffer_size: int) -> tuple[bytes, tuple[str, int]]:
                return encode_dataset(LAN_X_HEADER, b"\x63\x01"), ("127.0.0.1", 21105)

            def close(self) -> None:
                return None

        socket = FakeDatagramSocket()
        transport = Z21LanTransport(socket_factory=lambda: socket)
        transport.open()
        track = Z21TrackSystem(transport)
        track.register_train("T1", 101)
        self.assertFalse(track.set_train_speed("T1", 0.5).accepted)
        self.assertTrue(transport.check_connection().connected)
        self.assertTrue(track.set_train_speed("T1", 0.5).accepted)
        self.assertTrue(track.set_power(False).accepted)
        self.assertFalse(track.get_snapshot().powered)
        self.assertTrue(track.set_power(True).accepted)
        self.assertTrue(track.get_snapshot().powered)
        self.assertGreaterEqual(len(socket.sent), 2)
        transport.close()

    def test_z21_track_power_command_has_documented_xbus_shape(self) -> None:
        packet = decode_dataset(build_set_track_power(False))
        self.assertEqual(packet.header, LAN_X_HEADER)
        self.assertEqual(packet.data[:2], b"\x21\x80")

    def test_rbus_feedback_decoder_and_real_track_occupancy_mapping(self) -> None:
        feedback_packet = encode_dataset(LAN_RMBUS_DATACHANGED, bytes((0, 0b10000001)) + bytes(9))
        feedback = decode_rbus_feedback(feedback_packet)
        self.assertEqual(feedback.active_contacts, ((1, 1), (1, 8)))
        self.assertEqual(build_rbus_get_data(0), b"\x05\x00\x81\x00\x00")

        class FeedbackSocket:
            def __init__(self) -> None:
                self.responses = [encode_dataset(LAN_X_HEADER, b"\x63\x01"), feedback_packet]

            def settimeout(self, _value: float) -> None:
                return None

            def sendto(self, data: bytes, address: tuple[str, int]) -> int:
                return len(data)

            def recvfrom(self, _buffer_size: int) -> tuple[bytes, tuple[str, int]]:
                return self.responses.pop(0), ("127.0.0.1", 21105)

            def close(self) -> None:
                return None

        transport = Z21LanTransport(socket_factory=FeedbackSocket)
        transport.open()
        track = Z21TrackSystem(transport)
        track.bind_feedback(1, 1, "B01")
        self.assertTrue(transport.check_connection().connected)
        self.assertTrue(track.poll_feedback((0,))[0].accepted)
        self.assertEqual(track.get_snapshot().occupied_blocks, {"B01": ("sensor:1:1",)})
        transport.close()

    def test_rbus_feedback_failure_is_reported_unhealthy(self) -> None:
        class FailingFeedbackSocket:
            def __init__(self) -> None:
                self.checks = 0

            def settimeout(self, _value: float) -> None:
                return None

            def sendto(self, data: bytes, address: tuple[str, int]) -> int:
                return len(data)

            def recvfrom(self, _buffer_size: int) -> tuple[bytes, tuple[str, int]]:
                self.checks += 1
                if self.checks == 1:
                    return encode_dataset(LAN_X_HEADER, b"\x63\x01"), ("127.0.0.1", 21105)
                raise TimeoutError("feedback timeout")

            def close(self) -> None:
                return None

        transport = Z21LanTransport(socket_factory=FailingFeedbackSocket)
        transport.open()
        track = Z21TrackSystem(transport)
        track.bind_feedback(1, 1, "B01")
        self.assertTrue(transport.check_connection().connected)
        result = track.poll_feedback((0,))[0]
        self.assertFalse(result.accepted)
        self.assertFalse(track.feedback_healthy)
        self.assertIn("feedback timeout", track.feedback_error)
        transport.close()


if __name__ == "__main__":
    unittest.main()
