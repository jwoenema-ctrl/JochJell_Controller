"""Immutable domain models for the model railway controller.

These models describe layout and train state, but intentionally do not know
how state is stored or how a command reaches a real or simulated railway.
Collections on :class:`LayoutSnapshot` are tuples so snapshots can be safely
shared between readers and state subscribers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Any, Iterable, Mapping, TypeVar


class BlockState(str, Enum):
    """Operational state of a track block."""

    FREE = "free"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    OUT_OF_SERVICE = "out_of_service"


class TurnoutPosition(str, Enum):
    """The route currently selected by a turnout."""

    UNKNOWN = "unknown"
    STRAIGHT = "straight"
    DIVERGING = "diverging"


class SignalAspect(str, Enum):
    """Common signal aspects understood by the domain layer."""

    OFF = "off"
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    SHUNTING = "shunting"


class TrainMode(str, Enum):
    """How a train receives movement decisions."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"
    STOPPED = "stopped"


class TrainStatus(str, Enum):
    """Current high-level operating state of a train."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"


class ScheduleStatus(str, Enum):
    """Lifecycle state of a schedule."""

    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_finite(value: float, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)


def _require_non_negative(value: float, field_name: str) -> float:
    result = _require_finite(value, field_name)
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _unique_ids(values: Iterable[str], field_name: str, *, allow_self: str | None = None) -> tuple[str, ...]:
    result = tuple(_require_text(value, field_name) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must not contain duplicate IDs")
    if allow_self is not None and allow_self in result:
        raise ValueError(f"{field_name} must not contain the entity's own ID")
    return result


def _require_reference(value: str, field_name: str, target_name: str, target_ids: set[str]) -> None:
    """Require one cross-reference to identify an entity in the snapshot."""

    if value not in target_ids:
        raise ValueError(f"{field_name} references unknown {target_name} ID: {value}")


@dataclass(frozen=True, slots=True)
class Point:
    """A two-dimensional layout coordinate used by graph heuristics."""

    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _require_finite(self.x, "x"))
        object.__setattr__(self, "y", _require_finite(self.y, "y"))


@dataclass(frozen=True, slots=True)
class PhotoScan:
    """A photo-scan asset that can be anchored to the layout viewer."""

    id: str
    label: str
    description: str = ""
    image: str | None = None
    anchor: Point | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "label", _require_text(self.label, "label"))
        object.__setattr__(self, "description", self.description.strip())
        if self.image is not None and not isinstance(self.image, str):
            raise ValueError("image must be a string path or URL")
        if self.anchor is not None and not isinstance(self.anchor, Point):
            raise ValueError("anchor must be a Point")


@dataclass(frozen=True, slots=True)
class Block:
    """A contiguous section of track that can be occupied or reserved."""

    id: str
    name: str = ""
    length_mm: float = 0.0
    state: BlockState = BlockState.FREE
    neighbor_ids: tuple[str, ...] = ()
    occupied_by: str | None = None
    reserved_for: str | None = None
    waypoint_ids: tuple[str, ...] = ()
    platform_ids: tuple[str, ...] = ()
    position: Point | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "length_mm", _require_non_negative(self.length_mm, "length_mm"))
        object.__setattr__(
            self,
            "neighbor_ids",
            _unique_ids(self.neighbor_ids, "neighbor_ids", allow_self=self.id),
        )
        object.__setattr__(self, "waypoint_ids", _unique_ids(self.waypoint_ids, "waypoint_ids"))
        object.__setattr__(self, "platform_ids", _unique_ids(self.platform_ids, "platform_ids"))
        if self.state is BlockState.OCCUPIED and not self.occupied_by:
            raise ValueError("an occupied block must identify its train")
        if self.state is BlockState.RESERVED and not self.reserved_for:
            raise ValueError("a reserved block must identify the reserving train")


@dataclass(frozen=True, slots=True)
class Turnout:
    """A turnout connecting one entry block to either of two exit blocks."""

    id: str
    name: str = ""
    entry_block_id: str = ""
    straight_block_id: str = ""
    diverging_block_id: str = ""
    position: TurnoutPosition = TurnoutPosition.UNKNOWN
    locked_by: str | None = None
    address: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", self.name.strip())
        ids = (
            _require_text(self.entry_block_id, "entry_block_id"),
            _require_text(self.straight_block_id, "straight_block_id"),
            _require_text(self.diverging_block_id, "diverging_block_id"),
        )
        if len(set(ids)) != 3:
            raise ValueError("a turnout must have three distinct block IDs")
        if self.address is not None and not 0 <= int(self.address) <= 0xFFFF:
            raise ValueError("address must fit the Z21 accessory address range")


@dataclass(frozen=True, slots=True)
class Station:
    """A named passenger or operational location on the layout."""

    id: str
    name: str
    block_ids: tuple[str, ...] = ()
    platform_ids: tuple[str, ...] = ()
    waypoint_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "block_ids", _unique_ids(self.block_ids, "block_ids"))
        object.__setattr__(self, "platform_ids", _unique_ids(self.platform_ids, "platform_ids"))
        object.__setattr__(self, "waypoint_ids", _unique_ids(self.waypoint_ids, "waypoint_ids"))


@dataclass(frozen=True, slots=True)
class Signal:
    """A signal associated with a block and the block it protects."""

    id: str
    name: str = ""
    block_id: str = ""
    protects_block_id: str = ""
    aspect: SignalAspect = SignalAspect.RED
    address: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "block_id", _require_text(self.block_id, "block_id"))
        object.__setattr__(
            self,
            "protects_block_id",
            _require_text(self.protects_block_id, "protects_block_id"),
        )
        if self.address is not None and not 0 <= int(self.address) <= 0xFFFF:
            raise ValueError("address must fit the Z21 accessory address range")


@dataclass(frozen=True, slots=True)
class Waypoint:
    """A named routing point that can connect blocks or other graph nodes."""

    id: str
    name: str = ""
    connected_node_ids: tuple[str, ...] = ()
    position: Point | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(
            self,
            "connected_node_ids",
            _unique_ids(self.connected_node_ids, "connected_node_ids", allow_self=self.id),
        )


@dataclass(frozen=True, slots=True)
class Turntable:
    """A turntable node and the blocks currently accessible from it."""

    id: str
    name: str = ""
    connected_block_ids: tuple[str, ...] = ()
    aligned_block_id: str | None = None
    occupied_by: str | None = None
    position: Point | None = None
    address: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(
            self,
            "connected_block_ids",
            _unique_ids(self.connected_block_ids, "connected_block_ids", allow_self=self.id),
        )
        if self.aligned_block_id is not None and self.aligned_block_id not in self.connected_block_ids:
            raise ValueError("aligned_block_id must be one of connected_block_ids")
        if self.address is not None and not 0 <= int(self.address) <= 0xFFFF:
            raise ValueError("address must fit the Z21 accessory address range")


@dataclass(frozen=True, slots=True)
class Platform:
    """A platform edge attached to a station and a track block."""

    id: str
    name: str
    station_id: str
    block_id: str
    length_mm: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "station_id", _require_text(self.station_id, "station_id"))
        object.__setattr__(self, "block_id", _require_text(self.block_id, "block_id"))
        object.__setattr__(self, "length_mm", _require_non_negative(self.length_mm, "length_mm"))


@dataclass(frozen=True, slots=True)
class TrainModelInfo:
    """Catalog and decoder metadata for a physical model train."""

    manufacturer: str = ""
    catalogue_number: str = ""
    prototype: str = ""
    era: str = ""
    decoder_type: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("manufacturer", "catalogue_number", "prototype", "era", "decoder_type", "notes"):
            object.__setattr__(self, field_name, getattr(self, field_name).strip())


@dataclass(frozen=True, slots=True)
class Train:
    """A locomotive or consist known to the controller."""

    id: str
    name: str
    model: TrainModelInfo = TrainModelInfo()
    decoder_address: int | None = None
    length_mm: float = 0.0
    max_speed_kmh: float = 0.0
    mode: TrainMode = TrainMode.MANUAL
    status: TrainStatus = TrainStatus.STOPPED
    speed_kmh: float = 0.0
    current_block_id: str | None = None
    destination_block_id: str | None = None
    consist_ids: tuple[str, ...] = ()
    mass_g: float = 0.0
    requested_speed_kmh: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        if self.decoder_address is not None and not 1 <= self.decoder_address <= 9999:
            raise ValueError("decoder_address must be between 1 and 9999")
        object.__setattr__(self, "length_mm", _require_non_negative(self.length_mm, "length_mm"))
        object.__setattr__(self, "max_speed_kmh", _require_non_negative(self.max_speed_kmh, "max_speed_kmh"))
        object.__setattr__(self, "speed_kmh", _require_non_negative(self.speed_kmh, "speed_kmh"))
        object.__setattr__(self, "mass_g", _require_non_negative(self.mass_g, "mass_g"))
        if self.requested_speed_kmh is not None:
            object.__setattr__(self, "requested_speed_kmh", _require_non_negative(self.requested_speed_kmh, "requested_speed_kmh"))
            if self.max_speed_kmh and self.requested_speed_kmh > self.max_speed_kmh:
                raise ValueError("requested_speed_kmh must not exceed max_speed_kmh")
        if self.max_speed_kmh and self.speed_kmh > self.max_speed_kmh:
            raise ValueError("speed_kmh must not exceed max_speed_kmh")
        object.__setattr__(self, "consist_ids", _unique_ids(self.consist_ids, "consist_ids", allow_self=self.id))


@dataclass(frozen=True, slots=True)
class ScheduleStop:
    """A scheduled stop at a station, expressed in seconds from schedule start."""

    station_id: str
    platform_id: str | None = None
    arrival_seconds: float | None = None
    departure_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_id", _require_text(self.station_id, "station_id"))
        if self.platform_id is not None:
            object.__setattr__(self, "platform_id", _require_text(self.platform_id, "platform_id"))
        for field_name in ("arrival_seconds", "departure_seconds"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _require_non_negative(value, field_name))
        if (
            self.arrival_seconds is not None
            and self.departure_seconds is not None
            and self.departure_seconds < self.arrival_seconds
        ):
            raise ValueError("departure_seconds must not precede arrival_seconds")


@dataclass(frozen=True, slots=True)
class Schedule:
    """An ordered list of station stops assigned to one train."""

    id: str
    name: str
    train_id: str
    stops: tuple[ScheduleStop, ...] = ()
    status: ScheduleStatus = ScheduleStatus.PLANNED
    repeat: bool = False
    origin: str = ""
    destination: str = ""
    route_label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "train_id", _require_text(self.train_id, "train_id"))
        stops = tuple(self.stops)
        if not stops:
            raise ValueError("a schedule must contain at least one stop")
        object.__setattr__(self, "stops", stops)
        for field_name in ("origin", "destination", "route_label"):
            object.__setattr__(self, field_name, getattr(self, field_name).strip())


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    """A named, reusable path or routine flow through the layout graph."""

    id: str
    name: str
    source_block_id: str = ""
    target_block_id: str = ""
    node_ids: tuple[str, ...] = ()
    algorithm: str = "a_star"
    enabled: bool = True
    flow: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_text(self.id, "id"))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        source = str(self.source_block_id or "").strip()
        target = str(self.target_block_id or "").strip()
        nodes = tuple(_require_text(item, "node_ids") for item in self.node_ids)
        flow = tuple(dict(item) for item in self.flow if isinstance(item, Mapping))
        if not nodes and not flow:
            raise ValueError("route must contain at least one graph node")
        if nodes and (not source or not target):
            raise ValueError("graph routes require source_block_id and target_block_id")
        if nodes and (nodes[0] != source or nodes[-1] != target):
            raise ValueError("route node_ids must start at source_block_id and end at target_block_id")
        if len(set(nodes)) != len(nodes):
            raise ValueError("route node_ids must not contain duplicate graph nodes")
        algorithm = str(self.algorithm).strip().lower()
        if algorithm not in {"a_star", "bfs", "stationary"}:
            raise ValueError("route algorithm must be a_star, bfs, or stationary")
        if nodes and algorithm == "stationary":
            raise ValueError("graph routes cannot use the stationary algorithm")
        object.__setattr__(self, "source_block_id", source)
        object.__setattr__(self, "target_block_id", target)
        object.__setattr__(self, "node_ids", nodes)
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "flow", flow)


@dataclass(frozen=True, slots=True)
class ConnectionSpeedLimit:
    """One directed connection, in scale km/h; overrides replace the default."""

    from_block_id: str
    to_block_id: str
    speed_limit_kmh: float | None = None
    train_speed_limits: tuple[tuple[str, float], ...] = ()

    @property
    def id(self) -> str:
        return f"{self.from_block_id}>{self.to_block_id}"

    def __post_init__(self) -> None:
        _require_text(self.from_block_id, "from_block_id")
        _require_text(self.to_block_id, "to_block_id")
        if self.from_block_id == self.to_block_id:
            raise ValueError("connection endpoints must differ")
        def speed(value: float) -> float:
            if isinstance(value, bool):
                raise ValueError("speed limit must be a number, not a boolean")
            return _require_non_negative(value, "speed limit")
        if self.speed_limit_kmh is not None:
            object.__setattr__(self, "speed_limit_kmh", speed(self.speed_limit_kmh))
        overrides = tuple((_require_text(key, "train_id"), speed(value)) for key, value in self.train_speed_limits)
        if len(dict(overrides)) != len(overrides):
            raise ValueError("duplicate train speed overrides")
        object.__setattr__(self, "train_speed_limits", overrides)


_EntityT = TypeVar("_EntityT")


@dataclass(frozen=True, slots=True)
class LayoutSnapshot:
    """A complete immutable view of the layout and known trains."""

    revision: int = 0
    blocks: tuple[Block, ...] = ()
    turnouts: tuple[Turnout, ...] = ()
    stations: tuple[Station, ...] = ()
    signals: tuple[Signal, ...] = ()
    waypoints: tuple[Waypoint, ...] = ()
    turntables: tuple[Turntable, ...] = ()
    platforms: tuple[Platform, ...] = ()
    trains: tuple[Train, ...] = ()
    schedules: tuple[Schedule, ...] = ()
    routes: tuple[RouteDefinition, ...] = ()
    scans: tuple[PhotoScan, ...] = ()
    connection_limits: tuple[ConnectionSpeedLimit, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("revision must be a non-negative integer")
        for field_name in (
            "blocks",
            "turnouts",
            "stations",
            "signals",
            "waypoints",
            "turntables",
            "platforms",
            "trains",
            "schedules",
            "routes",
            "scans",
            "connection_limits",
        ):
            values = tuple(getattr(self, field_name))
            ids = tuple(getattr(value, "id") for value in values)
            if len(set(ids)) != len(ids):
                raise ValueError(f"{field_name} must not contain duplicate IDs")
            object.__setattr__(self, field_name, values)

        block_ids = {block.id for block in self.blocks}
        station_ids = {station.id for station in self.stations}
        station_by_id = {station.id: station for station in self.stations}
        waypoint_ids = {waypoint.id for waypoint in self.waypoints}
        turntable_ids = {turntable.id for turntable in self.turntables}
        platform_ids = {platform.id for platform in self.platforms}
        train_ids = {train.id for train in self.trains}
        connections = {(b.id, n) for b in self.blocks for n in b.neighbor_ids}
        for turnout in self.turnouts:
            for other in (turnout.straight_block_id, turnout.diverging_block_id):
                connections.update(((turnout.entry_block_id, other), (other, turnout.entry_block_id)))
        for rule in self.connection_limits:
            if (rule.from_block_id, rule.to_block_id) not in connections:
                raise ValueError(f"speed limit references missing connection: {rule.id}")
            for train_id, _ in rule.train_speed_limits:
                _require_reference(train_id, rule.id, "train", train_ids)
        graph_node_ids = block_ids | waypoint_ids | turntable_ids
        for route in self.routes:
            for node_id in route.node_ids:
                _require_reference(node_id, f"route {route.id}.node_ids", "graph node", graph_node_ids)
        platform_by_id = {platform.id: platform for platform in self.platforms}

        def require_each(values: Iterable[str], field_name: str, target_name: str, target_ids: set[str]) -> None:
            for value in values:
                _require_reference(value, field_name, target_name, target_ids)

        for block in self.blocks:
            require_each(block.neighbor_ids, f"block {block.id}.neighbor_ids", "block", block_ids)
            require_each(block.waypoint_ids, f"block {block.id}.waypoint_ids", "waypoint", waypoint_ids)
            require_each(block.platform_ids, f"block {block.id}.platform_ids", "platform", platform_ids)
            if block.occupied_by is not None:
                _require_reference(block.occupied_by, f"block {block.id}.occupied_by", "train", train_ids)
            if block.reserved_for is not None:
                _require_reference(block.reserved_for, f"block {block.id}.reserved_for", "train", train_ids)

        for turnout in self.turnouts:
            for field_name in ("entry_block_id", "straight_block_id", "diverging_block_id"):
                _require_reference(
                    getattr(turnout, field_name),
                    f"turnout {turnout.id}.{field_name}",
                    "block",
                    block_ids,
                )

        for station in self.stations:
            require_each(station.block_ids, f"station {station.id}.block_ids", "block", block_ids)
            require_each(station.platform_ids, f"station {station.id}.platform_ids", "platform", platform_ids)
            require_each(station.waypoint_ids, f"station {station.id}.waypoint_ids", "waypoint", waypoint_ids)

        for signal in self.signals:
            _require_reference(signal.block_id, f"signal {signal.id}.block_id", "block", block_ids)
            _require_reference(
                signal.protects_block_id,
                f"signal {signal.id}.protects_block_id",
                "block",
                block_ids,
            )

        for waypoint in self.waypoints:
            require_each(
                waypoint.connected_node_ids,
                f"waypoint {waypoint.id}.connected_node_ids",
                "graph node",
                graph_node_ids,
            )

        for turntable in self.turntables:
            require_each(
                turntable.connected_block_ids,
                f"turntable {turntable.id}.connected_block_ids",
                "block",
                block_ids,
            )
            if turntable.aligned_block_id is not None:
                _require_reference(
                    turntable.aligned_block_id,
                    f"turntable {turntable.id}.aligned_block_id",
                    "block",
                    block_ids,
                )
            if turntable.occupied_by is not None:
                _require_reference(
                    turntable.occupied_by,
                    f"turntable {turntable.id}.occupied_by",
                    "train",
                    train_ids,
                )

        for platform in self.platforms:
            _require_reference(platform.station_id, f"platform {platform.id}.station_id", "station", station_ids)
            _require_reference(platform.block_id, f"platform {platform.id}.block_id", "block", block_ids)

        for block in self.blocks:
            for platform_id in block.platform_ids:
                if platform_by_id[platform_id].block_id != block.id:
                    raise ValueError(f"block {block.id}.platform_ids entry {platform_id} must belong to the block")

        for station in self.stations:
            for platform_id in station.platform_ids:
                platform = platform_by_id[platform_id]
                if platform.station_id != station.id:
                    raise ValueError(f"station {station.id}.platform_ids entry {platform_id} must belong to the station")

        for platform in self.platforms:
            station = station_by_id[platform.station_id]
            if platform.block_id not in station.block_ids:
                raise ValueError(f"platform {platform.id}.block_id must belong to its station")

        for train in self.trains:
            if train.current_block_id is not None:
                _require_reference(
                    train.current_block_id,
                    f"train {train.id}.current_block_id",
                    "block",
                    block_ids,
                )
            if train.destination_block_id is not None:
                _require_reference(
                    train.destination_block_id,
                    f"train {train.id}.destination_block_id",
                    "block",
                    block_ids,
                )

        for schedule in self.schedules:
            _require_reference(schedule.train_id, f"schedule {schedule.id}.train_id", "train", train_ids)
            for stop_index, stop in enumerate(schedule.stops):
                if not isinstance(stop, ScheduleStop):
                    raise ValueError(f"schedule {schedule.id}.stops[{stop_index}] must be a ScheduleStop")
                _require_reference(
                    stop.station_id,
                    f"schedule {schedule.id}.stops[{stop_index}].station_id",
                    "station",
                    station_ids,
                )
                if stop.platform_id is not None:
                    _require_reference(
                        stop.platform_id,
                        f"schedule {schedule.id}.stops[{stop_index}].platform_id",
                        "platform",
                        platform_ids,
                    )

    @classmethod
    def empty(cls) -> "LayoutSnapshot":
        """Return an empty layout at revision zero."""

        return cls()

    def with_revision(self, revision: int) -> "LayoutSnapshot":
        """Return the same layout with a different state revision."""

        return replace(self, revision=revision)

    def get(self, entity_type: type[_EntityT], entity_id: str) -> _EntityT | None:
        """Find an entity by its dataclass type and ID."""

        collections = (
            self.blocks,
            self.turnouts,
            self.stations,
            self.signals,
            self.waypoints,
            self.turntables,
            self.platforms,
            self.trains,
            self.schedules,
            self.scans,
        )
        for collection in collections:
            for entity in collection:
                if isinstance(entity, entity_type) and entity.id == entity_id:
                    return entity
        return None

    def block(self, block_id: str) -> Block | None:
        """Find a block by ID."""

        return self.get(Block, block_id)

    def train(self, train_id: str) -> Train | None:
        """Find a train by ID."""

        return self.get(Train, train_id)
