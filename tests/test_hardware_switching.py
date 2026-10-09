"""Hardware replacement tests at the application boundary; no physical I/O."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from backend.api.server import ControllerApplication
from backend.infrastructure.hardware_network_track import NetworkTrackSystem
from backend.infrastructure.interfaces import CommandResult, ConnectionState, ConnectionStatus
from backend.infrastructure.simulation import SimulatedTrackSystem
from backend.infrastructure.train_database import RollingStockInventoryRecord
from backend.runtime import ControllerRuntime


class FakeTransport:
    def __init__(self, *, connected=True):
        self.connected = connected
        self.closed = False

    def connection_status(self):
        return ConnectionStatus(ConnectionState.CONNECTED if self.connected else ConnectionState.ERROR,
                                "fake station", "fixture connection failure" if not self.connected else "")

    def check_connection(self):
        return self.connection_status()

    def close(self):
        self.closed = True
        self.connected = False


class FakePhysicalTrack(NetworkTrackSystem):
    def __init__(self, *, connected=True, decoder_protocol="dcc", power_accepted=True):
        super().__init__(FakeTransport(connected=connected), decoder_protocol=decoder_protocol)
        self.commands = []
        self.power_accepted = power_accepted

    def validate_address(self, address, protocol):
        if protocol not in {"dcc", "mm", "mfx"}:
            raise ValueError("Unsupported decoder protocol")

    def _drive(self, address, speed, *, forward, speed_limit=None, protocol="dcc"):
        self.commands.append(("drive", address, speed, protocol))
        return CommandResult(True, "set_train_speed")

    def _function(self, address, number, enabled, *, protocol="dcc"):
        self.commands.append(("function", address, number, enabled, protocol))
        return CommandResult(True, "set_loco_function")

    def set_power(self, enabled):
        self.commands.append(("power", bool(enabled)))
        if self.power_accepted:
            self._snapshot = replace(self._snapshot, powered=bool(enabled))
        return CommandResult(self.power_accepted, "set_power", "fixture power rejection" if not self.power_accepted else "")

    def _read_feedback(self, device, contacts):
        return CommandResult(True, "poll_feedback"), {contact: False for contact in contacts}


class HardwareSwitchingTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()
        self.app.stop_motion_clock()
        self.addCleanup(self.app.close)

    def select(self, system="ecos", *, protocol="dcc"):
        self.app.update_settings({"hardware": {"system": system, "host": "127.0.0.1",
                                               "decoder_protocol": protocol}})

    def factory(self, physical):
        return lambda config, **_: SimulatedTrackSystem() if config["system"] == "simulation" else physical

    def connect(self, physical):
        with patch.object(ControllerRuntime, "create_track", side_effect=self.factory(physical)):
            return self.app.command({"type": "connect_hardware"})

    def test_switch_keeps_plan_clock_catalogue_and_routines_but_stops_motion(self):
        self.app.command({"type": "save_automation_program", "program": {
            "id": "retained-routine", "name": "Lights and wait", "train_id": "t1",
            "blocks": [{"type": "function", "function_number": 0, "enabled": True},
                       {"type": "wait", "duration_s": 20}],
        }})
        self.app.set_world_clock("14:23")
        runtime = self.app.runtime
        scheduler = runtime.scheduler
        train_database = runtime.train_database
        before = dict(blocks=deepcopy(self.app.blocks), connections=deepcopy(self.app._ui_connections()),
                      schedules=deepcopy(self.app.schedules), routes=deepcopy(self.app.routes),
                      programs=deepcopy(self.app.automation_programs_state()),
                      clock=scheduler.world_current_tick)
        before_trains = {t["id"]: (t.get("address"), t.get("name"), deepcopy(t.get("consist"))) for t in self.app.trains}
        self.select()
        physical = FakePhysicalTrack()
        state = self.connect(physical)
        self.assertIs(self.app.runtime, runtime)
        self.assertIs(runtime.scheduler, scheduler)
        self.assertIs(runtime.train_database, train_database)
        for name in ("blocks", "schedules", "routes"):
            self.assertEqual(getattr(self.app, name), before[name])
        self.assertEqual(self.app._ui_connections(), before["connections"])
        self.assertEqual(self.app.automation_programs_state(), before["programs"])
        self.assertEqual(scheduler.world_current_tick, before["clock"])
        self.assertEqual({t["id"]: (t.get("address"), t.get("name"), t.get("consist")) for t in self.app.trains}, before_trains)
        self.assertFalse(self.app.track_power)
        self.assertTrue(all(t["mode"] == "stopped" and t["speed"] == 0 for t in self.app.trains))
        self.assertFalse(any(command[0] == "drive" and command[2] > 0 for command in physical.commands))
        self.assertTrue(all(not command[1] for command in physical.commands if command[0] == "power"))
        self.assertEqual(state["runtime"]["hardware_system"], "ecos")

    def test_disconnect_closes_physical_station_and_leaves_stopped_simulator(self):
        self.select()
        physical = FakePhysicalTrack()
        self.connect(physical)
        self.app.command({"type": "power", "enabled": True})
        with patch.object(ControllerRuntime, "create_track", side_effect=self.factory(physical)):
            state = self.app.command({"type": "disconnect_hardware"})
        self.assertTrue(physical.transport.closed)
        self.assertIsInstance(self.app.runtime.track, SimulatedTrackSystem)
        self.assertFalse(self.app.track_power)
        self.assertFalse(self.app.runtime.track.get_snapshot().powered)
        self.assertTrue(all(t["mode"] == "stopped" for t in self.app.trains))
        self.assertEqual(state["runtime"]["hardware_system"], "simulation")

    def test_failed_connection_closes_candidate_and_falls_back_safely(self):
        self.select()
        physical = FakePhysicalTrack(connected=False)
        with self.assertRaisesRegex(ValueError, "fixture connection failure"):
            self.connect(physical)
        self.assertTrue(physical.transport.closed)
        self.assertIsInstance(self.app.runtime.track, SimulatedTrackSystem)
        self.assertEqual(self.app.hardware_system, "simulation")
        self.assertFalse(self.app.track_power)
        self.assertTrue(all(t["mode"] == "stopped" for t in self.app.trains))
        self.assertTrue(any(event["type"] == "hardware_connection_failed" for event in self.app.events))

    def test_candidate_must_confirm_power_off_before_activation(self):
        self.select()
        physical = FakePhysicalTrack(power_accepted=False)
        with self.assertRaisesRegex(ValueError, "fixture power rejection"):
            self.connect(physical)
        self.assertTrue(physical.transport.closed)
        self.assertIsInstance(self.app.runtime.track, SimulatedTrackSystem)

    def test_unsupported_train_protocol_remains_in_catalogue_without_binding(self):
        self.app.trains[0]["decoder_protocol"] = "mfx"
        retained_id = self.app.trains[0]["id"]
        self.select("z21")
        physical = FakePhysicalTrack()
        self.connect(physical)
        self.assertTrue(any(t["id"] == retained_id and t["decoder_protocol"].lower() == "mfx" for t in self.app.trains))
        self.assertIsNotNone(self.app.runtime.train_database.get_details(retained_id))
        self.assertNotIn(retained_id, self.app.runtime.dispatcher.trains)
        self.assertNotIn(retained_id, physical._train_addresses)

    def test_rolling_stock_keeps_dcc_protocol_when_station_default_is_motorola(self):
        self.app.runtime.train_database.upsert_inventory(RollingStockInventoryRecord(
            item_id="lit-coach", name="Lit coach", quantity=1, decoder_address=44,
            decoder_functions=({"function_number": 0, "name": "Lights"},)))
        self.app.trains[0].setdefault("consist", []).append({"id": "coach-instance", "catalogue_id": "lit-coach"})
        self.select(protocol="mm")
        physical = FakePhysicalTrack(decoder_protocol="mm")
        self.connect(physical)
        self.app.command({"type": "power", "enabled": True})
        self.app.command({"type": "set_rolling_stock_function", "train_id": self.app.trains[0]["id"],
                          "item_id": "lit-coach", "function_number": 0, "enabled": True})
        self.assertIn(("function", 44, 0, True, "dcc"), physical.commands)

    def test_same_numeric_motorola_address_does_not_share_dcc_car_function_state(self):
        self.app.trains[0].update(address=44, decoder_protocol="mm")
        self.app.runtime.train_database.upsert_inventory(RollingStockInventoryRecord(
            item_id="lit-coach", name="Lit coach", quantity=1, decoder_address=44,
            decoder_functions=({"function_number": 0, "name": "Lights"},)))
        self.app.trains[0].setdefault("consist", []).append({"id": "coach-instance", "catalogue_id": "lit-coach"})
        self.select(protocol="mm")
        self.connect(FakePhysicalTrack(decoder_protocol="mm"))
        self.app.command({"type": "power", "enabled": True})
        self.app.command({"type": "set_rolling_stock_function", "train_id": self.app.trains[0]["id"],
                          "item_id": "lit-coach", "function_number": 0, "enabled": True})
        self.assertEqual(self.app._rolling_stock_function_states[44]["0"], True)
        self.assertNotEqual(self.app.trains[0]["decoder_function_states"].get("0"), True)
        self.app.command({"type": "set_train_function", "train_id": self.app.trains[0]["id"],
                          "function_number": 0, "enabled": False})
        self.assertEqual(self.app._rolling_stock_function_states[44]["0"], True)

    def test_installation_registration_failure_closes_station_and_falls_back(self):
        self.select()
        physical = FakePhysicalTrack()
        physical.register_train = lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("fixture registration failure"))
        with self.assertRaisesRegex(ValueError, "fixture registration failure"):
            self.connect(physical)
        self.assertTrue(physical.transport.closed)
        self.assertIsInstance(self.app.runtime.track, SimulatedTrackSystem)
        self.assertEqual(self.app.hardware_system, "simulation")
        self.assertFalse(self.app.track_power)
        self.assertTrue(all(t["mode"] == "stopped" for t in self.app.trains))

    def test_generic_status_and_capabilities_follow_active_station(self):
        self.select("marklin_cs3")
        state = self.connect(FakePhysicalTrack())
        status = state["runtime"]
        self.assertEqual(status["hardware_system"], "marklin_cs3")
        self.assertEqual(status["hardware_label"], "Märklin Central Station 3")
        self.assertTrue(status["hardware_capabilities"]["functions"])
        self.assertFalse(status["hardware_capabilities"]["programming"])
        self.assertIsNone(status["active_z21_host"])
        self.assertEqual(status["hardware_decoder_protocols"], ["dcc", "mm", "mfx"])


if __name__ == "__main__":
    unittest.main()
