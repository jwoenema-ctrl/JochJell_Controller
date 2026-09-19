"""Default dependency-injection composition for simulation-first operation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .core import EventController, LayoutController, StateController
from .core.models import BlockState
from .core.routing import RouteAlgorithm, find_route
from .infrastructure.interfaces import ConnectionState, ConnectionStatus, TrackSystem
from .infrastructure.layout_repository import SQLiteLayoutRepository
from .infrastructure.simulation import SimulatedTrackSystem
from .infrastructure.train_database import SQLiteTrainDatabase
from .infrastructure.real_track import Z21TrackSystem
from .infrastructure.z21 import Z21LanTransport
from .services.avoidance import AvoidanceDetector
from .services.connection import ConnectionChecker
from .services.calibration import TrainCalibrationService
from .services.coordinate_execution import CoordinateMovementExecutor
from .services.automation_recording import AutomationRecordingService
from .services.dispatcher import ControlMode, DispatchCycle, Dispatcher
from .services.interlocking import MovementAuthorityService
from .services.route_updater import ConstantRouteUpdater
from .services.scheduler import TimetableService
from .services.system_switcher import AutomaticSystemSwitcher


class SimulationConnectionProvider:
    """Connection provider used by the default simulation runtime."""

    def check_connection(self) -> ConnectionStatus:
        return ConnectionStatus(ConnectionState.CONNECTED, "simulation", "deterministic simulator")

    def connection_status(self) -> ConnectionStatus:
        return self.check_connection()


@dataclass
class ControllerRuntime:
    """Compose the modular services used by the first runnable milestone."""

    track: TrackSystem
    layout: LayoutController
    state: StateController
    events: EventController
    scheduler: TimetableService
    route_updater: ConstantRouteUpdater
    avoidance: AvoidanceDetector
    dispatcher: Dispatcher
    interlocking: MovementAuthorityService
    mode_switcher: AutomaticSystemSwitcher
    connection: ConnectionChecker
    train_database: SQLiteTrainDatabase
    layout_repository: SQLiteLayoutRepository
    calibration: TrainCalibrationService
    coordinate_movement: CoordinateMovementExecutor
    recording: AutomationRecordingService

    @classmethod
    def create(cls, *, database_path: str = ":memory:") -> "ControllerRuntime":
        track = SimulatedTrackSystem()
        return cls._compose(track, database_path=database_path, connection=ConnectionChecker(SimulationConnectionProvider()))

    @classmethod
    def create_z21(
        cls,
        host: str,
        *,
        port: int = 21105,
        database_path: str = ":memory:",
        feedback_map: Mapping[tuple[int, int], str] | None = None,
    ) -> "ControllerRuntime":
        """Create a real-track runtime; no train command is sent before a check succeeds."""

        transport = Z21LanTransport(host, port=port)
        transport.open()
        track = Z21TrackSystem(transport, feedback_map=feedback_map)
        return cls._compose(track, database_path=database_path, connection=ConnectionChecker(track))

    @classmethod
    def _compose(
        cls,
        track: TrackSystem,
        *,
        database_path: str,
        connection: ConnectionChecker,
    ) -> "ControllerRuntime":
        state = StateController()
        events = EventController()
        layout = LayoutController(state_controller=state, event_controller=events)
        route_updater = ConstantRouteUpdater()
        avoidance = AvoidanceDetector()
        interlocking = MovementAuthorityService()
        dispatcher = Dispatcher(track, avoidance_detector=avoidance, route_updater=route_updater, interlocking=interlocking)
        database = SQLiteTrainDatabase(database_path)
        return cls(
            track=track,
            layout=layout,
            state=state,
            events=events,
            scheduler=TimetableService(),
            route_updater=route_updater,
            avoidance=avoidance,
            dispatcher=dispatcher,
            interlocking=interlocking,
            mode_switcher=AutomaticSystemSwitcher(dispatcher),
            connection=connection,
            train_database=database,
            layout_repository=SQLiteLayoutRepository(database_path),
            calibration=TrainCalibrationService(dispatcher, track, database),
            coordinate_movement=CoordinateMovementExecutor(dispatcher, track),
            recording=AutomationRecordingService(),
        )

    def add_train(
        self,
        train_id: str,
        block_id: str,
        *,
        route: tuple[str, ...] = (),
        address: int | None = None,
    ) -> None:
        """Register one train in the simulator and dispatcher."""

        if isinstance(self.track, SimulatedTrackSystem):
            self.track.add_train(train_id, block_id, route=route)
        elif isinstance(self.track, Z21TrackSystem):
            if address is None:
                raise ValueError("address is required when registering a real Z21 train")
            self.track.register_train(train_id, address)
        else:
            raise TypeError("unsupported track system")
        self.dispatcher.register_train(train_id)
        self.route_updater.register_train(train_id, route or (block_id,))

    def tick(self, count: int = 1) -> DispatchCycle:
        """Advance simulation time and run one safe dispatch cycle per tick."""

        cycle: DispatchCycle | None = None
        for _ in range(max(0, count)):
            if isinstance(self.track, Z21TrackSystem):
                connection = self.connection.check()
                if not connection.status.connected:
                    self.dispatcher.emergency_stop()
            self.track.tick()
            if isinstance(self.track, Z21TrackSystem) and self.track.feedback_groups():
                results = self.track.poll_feedback(self.track.feedback_groups())
                if any(not result.accepted for result in results):
                    self.dispatcher.emergency_stop()
            cycle = self.dispatcher.tick()
        if cycle is None:
            cycle = self.dispatcher.tick()
        return cycle

    def refresh_routes(
        self,
        destinations: Mapping[str, str],
        positions: Mapping[str, str] | None = None,
    ) -> dict[str, tuple[str, ...]]:
        """Recalculate plans and reservations without polling or commanding track.

        This is safe to run on a wall-clock timer. It deliberately never ticks
        the dispatcher, changes a train target, or sends a transport packet.
        Dispatch still performs its independent safety checks on every tick.
        """

        snapshot = self.track.get_snapshot()
        graph = self.layout.graph()
        locations = dict(positions or {})
        locations.update({motion.train_id: motion.block_id for motion in snapshot.trains if motion.block_id})
        blocked = tuple(block.id for block in self.layout.snapshot().snapshot.blocks if block.state is BlockState.OUT_OF_SERVICE)
        planned_routes: dict[str, tuple[str, ...]] = {}
        for train_id, control in self.dispatcher.trains.items():
            if control.mode is not ControlMode.AUTOMATIC:
                continue
            current = self.route_updater.desired_routes.get(train_id, ())
            start = str(locations.get(train_id, current[0] if current else "")).upper()
            goal = str(destinations.get(train_id, current[-1] if current else start)).upper()
            if graph.node(start) is None:
                self.route_updater.release_train(train_id)
                continue
            route = find_route(graph, start, goal, algorithm=RouteAlgorithm.A_STAR, blocked_nodes=blocked) if graph.node(goal) is not None else None
            values = route.node_ids if route is not None else (start,)
            self.route_updater.set_route(train_id, values)
            planned_routes[train_id] = values
        self.route_updater.update(snapshot.occupied_blocks)
        return planned_routes

    def close(self) -> None:
        self.coordinate_movement.close()
        self.calibration.close()
        self.train_database.close()
        self.layout_repository.close()
        if isinstance(self.track, Z21TrackSystem):
            self.track.transport.close()
