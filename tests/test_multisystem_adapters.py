"""Protocol fixtures exercised through real localhost UDP/TCP sockets.

These verify the client boundary, not physical compatibility with a station.
Packet fixtures follow Märklin CAN 2.0 and the ESU PC-interface specification.
"""

from contextlib import contextmanager
import re
import socket
import threading
import unittest

from backend.infrastructure.ecos import ECoSTrackSystem, ECoSTransport
from backend.infrastructure.marklin import CANFrame, MarklinTrackSystem, locomotive_id
from backend.core.models import ConnectionSpeedLimit
from backend.services.connection_speed import ConnectionSpeedPolicy


@contextmanager
def udp_station(handler):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.05)
    stopped = threading.Event()
    packets = []

    def serve():
        while not stopped.is_set():
            try:
                raw, peer = sock.recvfrom(4096)
                packets.append(raw)
                frame = CANFrame.decode(raw)
                for reply in handler(frame):
                    sock.sendto(reply.encode(), peer)
            except socket.timeout:
                pass
            except OSError:
                break

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield sock.getsockname()[1], packets
    finally:
        stopped.set()
        thread.join(1)
        sock.close()


def can_ack(frame):
    if frame.command == 0x18:
        return [CANFrame(0x18, bytes.fromhex("4353320000020000"), True)]
    return [CANFrame(frame.command, frame.data, True)]


@contextmanager
def tcp_station(handler, *, fragment=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    sock.settimeout(0.05)
    stopped = threading.Event()
    commands = []
    peers = []

    def serve():
        while not stopped.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            peers.append(conn)
            conn.settimeout(0.05)
            buf = b""
            try:
                while not stopped.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        command = line.decode().strip()
                        commands.append(command)
                        response = handler(command)
                        if response is None:
                            continue
                        payload = response.encode()
                        if fragment:
                            for offset in range(0, len(payload), 7):
                                conn.sendall(payload[offset:offset + 7])
                        else:
                            conn.sendall(payload)
            except OSError:
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield sock.getsockname()[1], commands
    finally:
        stopped.set()
        thread.join(1)
        sock.close()


def ecos_reply(command, text="", code=0):
    return f"<REPLY {command}>\n{text}<END {code} ({'OK' if code == 0 else 'NERROR_NOCONTROL'})>\n"


def ecos_handler(command):
    if command == "get(1, status)":
        return ecos_reply(command, "1 Status[GO]\n")
    if command == "queryObjects(10, addr, protocol)":
        return ecos_reply(command, "1007 addr[3] protocol[DCC128]\n1008 addr[3] protocol[MM28]\n")
    if command == "get(100, state, ports)":
        return ecos_reply(command, "100 state[0x8001] ports[16]\n")
    if command == "get(1300, protocol)":
        return ecos_reply(command, "1300 protocol[M4]\n")
    if command.startswith("create(10,"):
        return ecos_reply(command, "10 id[1200]\n")
    return ecos_reply(command)


class MarklinProtocolTests(unittest.TestCase):
    def test_documented_dcc_packet_and_protocol_local_ids(self):
        # CAN spec section 3.4 example: DCC address3 speed0x0120.
        frame = CANFrame(4, bytes.fromhex("0000c0030120"))
        self.assertEqual(frame.encode(), bytes.fromhex("00084711060000c00301200000"))
        self.assertEqual(CANFrame.decode(frame.encode()), frame)
        self.assertEqual(locomotive_id(3, "mm"), 3)
        self.assertEqual(locomotive_id(3, "mfx"), 0x4003)
        for raw in (b"\0" * 12, bytes.fromhex("00084711090000c00301200000")):
            with self.assertRaises(ValueError):
                CANFrame.decode(raw)

    def test_control_feedback_and_unsupported_programming_over_udp(self):
        def handler(frame):
            if frame.command == 0x11:
                return [CANFrame(0x11, frame.data + b"\0\1\0\0", True)]
            return can_ack(frame)
        with udp_station(handler) as (port, packets):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=0.2,
                feedback_map={(2, 17): "B1"})
            self.addCleanup(track.close)
            self.assertTrue(track.check_connection().connected)
            track.register_train("dcc", 3)
            track.register_train("mm", 3, decoder_protocol="mm")
            self.assertTrue(track.set_power(True).accepted)
            self.assertTrue(track.set_train_speed("dcc", .288).accepted)
            self.assertTrue(track.set_train_function("mm", 2, enabled=True).accepted)
            self.assertTrue(track.poll_feedback()[0].accepted)
            self.assertTrue(track.feedback_healthy)
            self.assertEqual(track.get_snapshot().occupied_blocks["B1"], ("sensor:2:17",))
            self.assertFalse(track.read_cv("dcc", 29)[0].accepted)
            self.assertTrue(track.set_turnout_by_address(1, output=1).accepted)
            decoded = [CANFrame.decode(packet) for packet in packets]
            self.assertIn(CANFrame(4, bytes.fromhex("0000c0030120")), decoded)
            self.assertIn(CANFrame(6, bytes.fromhex("000000030201")), decoded)
            self.assertIn(CANFrame(0x0B, bytes.fromhex("000038000101000a")), decoded)
            self.assertIn(CANFrame(0x0B, bytes.fromhex("000038000100")), decoded)

    def test_failed_feedback_preserves_occupancy_and_marks_unhealthy(self):
        fresh = [True]
        def handler(frame):
            if frame.command == 0x11:
                return [CANFrame(0x11, frame.data + b"\0\1\0\0", True)] if fresh[0] else []
            return can_ack(frame)
        with udp_station(handler) as (port, _):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=.05,
                feedback_map={(0, 1): "B1"})
            self.addCleanup(track.close)
            self.assertTrue(track.poll_feedback()[0].accepted)
            fresh[0] = False
            self.assertFalse(track.poll_feedback()[0].accepted)
            self.assertFalse(track.feedback_healthy)
            self.assertIn("B1", track.get_snapshot().occupied_blocks)

    def test_mismatched_ack_cannot_accept_speed_and_direction_failure_stops_sequence(self):
        def handler(frame):
            if frame.command == 5:
                return [CANFrame(5, b"\0\0\0\3\2", True)]
            return can_ack(frame)
        with udp_station(handler) as (port, packets):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=.05)
            self.addCleanup(track.close)
            track.register_train("t", 3)
            self.assertTrue(track.set_power(True).accepted)
            self.assertFalse(track.set_train_speed("t", .5).accepted)
            self.assertEqual(track.get_effective_speed("t"), 0)
            self.assertFalse(any(CANFrame.decode(p).command == 4 for p in packets))
            self.assertFalse(track.connection_status().connected)

    def test_route_speed_limits_survive_wire_protocol_change(self):
        with udp_station(can_ack) as (port, packets):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=.2)
            self.addCleanup(track.close)
            track.register_train("t", 3)
            self.assertTrue(track.set_power(True).accepted)
            track.configure_speed_limits(ConnectionSpeedPolicy(
                [ConnectionSpeedLimit("B1", "B2", speed_limit_kmh=20)], {"t": 100}))
            track.report_train_position("t", "B1", ("B1", "B2", "B3"))
            self.assertTrue(track.set_train_speed("t", .8).accepted)
            self.assertEqual(track.get_effective_speed("t"), .2)
            self.assertTrue(track.report_train_position("t", "B2", ("B1", "B2", "B3")).accepted)
            self.assertEqual(track.get_effective_speed("t"), .8)
            speed_values = [int.from_bytes(CANFrame.decode(p).data[4:6], "big")
                for p in packets if CANFrame.decode(p).command == 4]
            self.assertEqual(speed_values, [200, 800])

    def test_station_power_off_event_during_direction_prevents_drive(self):
        def handler(frame):
            if frame.command == 5:
                return [CANFrame(0, b"\0\0\0\0\0", True), *can_ack(frame)]
            return can_ack(frame)
        with udp_station(handler) as (port, packets):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=.2)
            self.addCleanup(track.close)
            track.register_train("t", 3)
            self.assertFalse(track.set_train_speed("t", .5).accepted)
            self.assertEqual(packets, [])
            self.assertTrue(track.set_power(True).accepted)
            self.assertFalse(track.set_train_speed("t", .5).accepted)
            self.assertFalse(track.get_snapshot().powered)
            self.assertFalse(any(CANFrame.decode(p).command == 4 for p in packets))

    def test_turnout_ack_failure_still_sends_release_and_has_station_timeout(self):
        def handler(frame):
            if frame.command == 0x0B and frame.data[5]:
                return []
            return can_ack(frame)
        with udp_station(handler) as (port, packets):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=.05)
            self.addCleanup(track.close)
            self.assertFalse(track.set_turnout_by_address(2, output=1).accepted)
            decoded = [CANFrame.decode(packet) for packet in packets]
            self.assertEqual(decoded, [CANFrame(0x0B, bytes.fromhex("000038010101000a")),
                                       CANFrame(0x0B, bytes.fromhex("000038010100"))])

    def test_turnout_release_failure_rejects_success(self):
        def handler(frame):
            return [] if frame.command == 0x0B and not frame.data[5] else can_ack(frame)
        with udp_station(handler) as (port, packets):
            track = MarklinTrackSystem("127.0.0.1", port, local_port=0, timeout=.05)
            self.addCleanup(track.close)
            result = track.set_turnout_by_address(2)
            self.assertFalse(result.accepted)
            self.assertIn("release", result.detail)
            self.assertEqual(len(packets), 2)
            self.assertFalse(track.connection_status().connected)


class ECoSProtocolTests(unittest.TestCase):
    def test_turnout_requires_station_bounded_pulse_configuration(self):
        for mode, duration, exists, accepted in (("PULSE", "250", True, True),
                                                ("SWITCH", "250", True, False),
                                                ("PULSE", "0", True, False),
                                                ("PULSE", "250", False, False)):
            with self.subTest(mode=mode, duration=duration, exists=exists):
                def handler(command):
                    if command == "queryObjects(11, addr, protocol)":
                        return ecos_reply(command, "20001 addr[3g,3r,4g,4r] protocol[DCC]\n" if exists else "")
                    if command == "get(20001, mode, duration)":
                        return ecos_reply(command, f"20001 mode[{mode}] duration[{duration}]\n")
                    return ecos_handler(command)
                with tcp_station(handler) as (port, commands):
                    track = ECoSTrackSystem("127.0.0.1", port, timeout=.2)
                    try:
                        self.assertEqual(track.set_turnout_by_address(3, output=1).accepted, accepted)
                        self.assertEqual("set(11, switch[DCC3g])" in commands, accepted)
                    finally:
                        track.close()

    def test_fragmented_replies_events_and_station_object_resolution(self):
        def handler(command):
            return "<EVENT 1009>\n1009 speed[0]\n<END 0 (OK)>\n" + ecos_handler(command)
        with tcp_station(handler, fragment=True) as (port, commands):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.5, feedback_map={(1, 16): "B1"})
            self.addCleanup(track.close)
            self.assertTrue(track.check_connection().connected)
            track.register_train("dcc", 3)
            track.register_train("mm", 3, decoder_protocol="mm")
            self.assertTrue(track.set_power(True).accepted)
            self.assertTrue(track.set_train_speed("dcc", .5).accepted)
            self.assertTrue(track.set_train_function("mm", 0, enabled=True).accepted)
            self.assertTrue(track.poll_feedback()[0].accepted)
            self.assertEqual(track.get_snapshot().occupied_blocks["B1"], ("sensor:1:16",))
            self.assertIn("request(1007, control)", commands)
            self.assertIn("set(1007, dir[0], speed[64])", commands)
            self.assertIn("set(1008, func[0, 1])", commands)
            self.assertFalse(any("force" in c for c in commands))

    def test_control_conflict_rejects_movement(self):
        def handler(command):
            if command.startswith("request("):
                return ecos_reply(command, code=25)
            return ecos_handler(command)
        with tcp_station(handler) as (port, commands):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.2)
            self.addCleanup(track.close)
            track.register_train("t", 3)
            self.assertTrue(track.set_power(True).accepted)
            result = track.set_train_speed("t", .5)
            self.assertFalse(result.accepted)
            self.assertIn("NERROR_NOCONTROL", result.detail)
            self.assertFalse(any(c.startswith("set(1007,") for c in commands))

    def test_creation_and_mfx_object_control_are_distinct(self):
        with tcp_station(ecos_handler) as (port, commands):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.2)
            self.addCleanup(track.close)
            track.register_train("new", 44)
            track.register_train("mfx", 1300, decoder_protocol="mfx")
            self.assertTrue(track.set_power(True).accepted)
            self.assertTrue(track.set_train_speed("new", .001).accepted)
            self.assertTrue(track.set_train_function("mfx", 5, enabled=True).accepted)
            self.assertIn("create(10, addr[44], protocol[DCC128], append)", commands)
            self.assertIn("set(1200, dir[0], speed[0])", commands)
            self.assertIn("set(1300, func[5, 1])", commands)
            self.assertFalse(any("create" in c and "1300" in c for c in commands))

    def test_timeout_disconnect_and_reconnect_reacquires_control(self):
        drop = [False]
        def handler(command):
            return None if drop[0] and command.startswith("set(") else ecos_handler(command)
        with tcp_station(handler) as (port, commands):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.05)
            self.addCleanup(track.close)
            track.register_train("t", 3)
            self.assertTrue(track.set_power(True).accepted)
            self.assertTrue(track.set_train_speed("t", .3).accepted)
            drop[0] = True
            self.assertFalse(track.set_train_speed("t", .4).accepted)
            self.assertFalse(track.connection_status().connected)
            self.assertFalse(track.get_snapshot().powered)
            drop[0] = False
            self.assertTrue(track.stop_train("t").accepted)
            self.assertEqual(commands.count("request(1007, control)"), 2)

    def test_feedback_missing_state_never_reports_clear(self):
        fail = [False]
        def handler(command):
            if command.startswith("get(100,") and fail[0]:
                return ecos_reply(command, "100 ports[16]\n")
            return ecos_handler(command)
        with tcp_station(handler) as (port, _):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.2, feedback_map={(1, 1): "B1"})
            self.addCleanup(track.close)
            self.assertTrue(track.poll_feedback()[0].accepted)
            fail[0] = True
            self.assertFalse(track.poll_feedback()[0].accepted)
            self.assertFalse(track.feedback_healthy)
            self.assertIn("B1", track.get_snapshot().occupied_blocks)

    def test_station_already_on_does_not_arm_motion_and_stop_event_prevents_drive(self):
        def handler(command):
            response = ecos_handler(command)
            if command.startswith("queryObjects("):
                response = "<EVENT 1>\n1 Status[STOP]\n<END 0 (OK)>\n" + response
            return response
        with tcp_station(handler) as (port, commands):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.2)
            self.addCleanup(track.close)
            self.assertTrue(track.check_connection().connected)
            self.assertFalse(track.get_snapshot().powered)
            track.register_train("t", 3)
            self.assertFalse(track.set_train_speed("t", .5).accepted)
            self.assertTrue(track.set_power(True).accepted)
            self.assertFalse(track.set_train_speed("t", .5).accepted)
            self.assertFalse(track.get_snapshot().powered)
            self.assertFalse(any(c.startswith("set(1007,") for c in commands))

    def test_reported_stop_cannot_be_overridden_by_successful_go_reply(self):
        def handler(command):
            if command == "set(1, go)":
                return ecos_reply(command, "1 Status[STOP]\n")
            return ecos_handler(command)
        with tcp_station(handler) as (port, _):
            track = ECoSTrackSystem("127.0.0.1", port, timeout=.2)
            self.addCleanup(track.close)
            self.assertFalse(track.set_power(True).accepted)
            self.assertFalse(track.transport.powered)
            self.assertFalse(track.get_snapshot().powered)


if __name__ == "__main__":
    unittest.main()
