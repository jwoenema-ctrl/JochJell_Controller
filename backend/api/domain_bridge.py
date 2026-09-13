"""Translate the browser-shaped state into the immutable core model.

The dashboard intentionally uses a compact JSON shape (lower-case block IDs,
pixel coordinates and display labels).  This module is the anti-corruption
layer between that shape and the typed layout/runtime model.  Keeping the
translation here means the HTTP handler does not become a second domain model.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from backend.core.models import (
    Block,
    BlockState,
    ConnectionSpeedLimit,
    LayoutSnapshot,
    Platform,
    Point,
    PhotoScan,
    Schedule,
    ScheduleStatus,
    ScheduleStop,
    Signal,
    SignalAspect,
    Station,
    Train,
    TrainMode,
    TrainModelInfo,
    TrainStatus,
    Turnout,
    TurnoutPosition,
    Turntable,
    Waypoint,
)


def _canonical_block_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.upper() if text else text


def _canonical_train_id(value: Any) -> str:
    text = str(value or "").strip()
    return {"t1": "train-101", "t2": "train-3"}.get(text, text)


def _ui_train_id(value: str) -> str:
    return {"train-101": "t1", "train-3": "t2"}.get(value, value)


def _position(value: Mapping[str, Any]) -> Point:
    return Point(float(value.get("x", 0)), float(value.get("y", 0)))


def _anchor(value: Any) -> Point | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("scan anchor must be an object")
    return Point(float(value.get("x", 0.5)), float(value.get("y", 0.5)))


def _time_seconds(value: Any) -> float:
    try:
        hours, minutes = (int(part) for part in str(value).split(":", 1))
    except (TypeError, ValueError):
        return 0.0
    return float((hours % 24) * 3600 + max(0, min(minutes, 59)) * 60)


def _optional_time_seconds(value: Any) -> float | None:
    """Parse an optional stop time expressed as seconds or ``HH:MM``."""

    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    return _time_seconds(value)


def _state(value: Any, occupied_by: str | None) -> BlockState:
    selected = str(value or "").lower()
    if occupied_by:
        return BlockState.OCCUPIED
    if selected in {BlockState.OCCUPIED.value, BlockState.RESERVED.value}:
        # These are live runtime facts, not durable editor metadata. A train
        # may have left since the last saved block label was written.
        return BlockState.FREE
    try:
        return BlockState(selected or BlockState.FREE.value)
    except ValueError:
        return BlockState.FREE


def snapshot_from_ui(
    *,
    blocks: Iterable[Mapping[str, Any]],
    turnouts: Iterable[Mapping[str, Any]],
    trains: Iterable[Mapping[str, Any]],
    schedules: Iterable[Mapping[str, Any]] = (),
    edges: Iterable[Mapping[str, Any]] = (),
    stations: Iterable[Mapping[str, Any]] = (),
    signals: Iterable[Mapping[str, Any]] = (),
    waypoints: Iterable[Mapping[str, Any]] = (),
    turntables: Iterable[Mapping[str, Any]] = (),
    platforms: Iterable[Mapping[str, Any]] = (),
    scans: Iterable[Mapping[str, Any]] = (),
    connection_limits: Iterable[Mapping[str, Any]] = (),
    revision: int = 0,
) -> LayoutSnapshot:
    """Build a validated domain snapshot from the current application state."""

    block_values = [dict(value) for value in blocks]
    train_values = [dict(value) for value in trains]
    train_by_id = {_canonical_train_id(value.get("id")): value for value in train_values}
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        left = _canonical_block_id(edge.get("from"))
        right = _canonical_block_id(edge.get("to"))
        if left and right and left != right:
            neighbours[left].add(right)
            neighbours[right].add(left)

    domain_blocks: list[Block] = []
    for value in block_values:
        block_id = _canonical_block_id(value.get("id"))
        if not block_id:
            continue
        occupants = [
            _canonical_train_id(train.get("id"))
            for train in train_values
            if _canonical_block_id(train.get("block_id", train.get("position"))) == block_id
        ]
        occupied_by = occupants[0] if occupants else None
        domain_blocks.append(
            Block(
                id=block_id,
                name=str(value.get("name", block_id)),
                length_mm=float(value.get("length_mm", 1000)),
                state=_state(value.get("status"), occupied_by),
                neighbor_ids=tuple(sorted(neighbours.get(block_id, set()))),
                occupied_by=occupied_by,
                platform_ids=tuple(str(item) for item in value.get("platform_ids", ())),
                position=_position(value),
            )
        )

    domain_turnouts: list[Turnout] = []
    for value in turnouts:
        turnout_id = str(value.get("id", "")).strip().upper()
        entry = _canonical_block_id(value.get("from", value.get("entry_block_id")))
        straight = _canonical_block_id(value.get("to", value.get("straight_block_id")))
        diverging = _canonical_block_id(value.get("alternate", value.get("diverging_block_id")))
        if not turnout_id or not entry or not straight or not diverging:
            continue
        selected = str(value.get("state", "unknown")).lower()
        position = {
            "straight": TurnoutPosition.STRAIGHT,
            "diverging": TurnoutPosition.DIVERGING,
        }.get(selected, TurnoutPosition.UNKNOWN)
        address = value.get("address")
        domain_turnouts.append(Turnout(turnout_id, str(value.get("name", turnout_id)), entry, straight, diverging, position, None, int(address) if address not in (None, "") else None))

    domain_signals: list[Signal] = []
    for value in signals:
        signal_id = str(value.get("id", "")).strip().upper()
        block_id = _canonical_block_id(value.get("block_id"))
        protects = _canonical_block_id(value.get("protects_block_id", value.get("protects")))
        if not signal_id or not block_id or not protects:
            continue
        try:
            aspect = SignalAspect(str(value.get("aspect", SignalAspect.RED.value)).lower())
        except ValueError:
            aspect = SignalAspect.RED
        address = value.get("address")
        domain_signals.append(Signal(signal_id, str(value.get("name", signal_id)), block_id, protects, aspect, int(address) if address not in (None, "") else None))

    domain_waypoints: list[Waypoint] = []
    for value in waypoints:
        waypoint_id = str(value.get("id", "")).strip().upper()
        connected = tuple(str(item).strip().upper() for item in value.get("connected_node_ids", value.get("connected", ())) if str(item).strip())
        if waypoint_id:
            domain_waypoints.append(Waypoint(waypoint_id, str(value.get("name", waypoint_id)), connected, _position(value)))

    domain_turntables: list[Turntable] = []
    for value in turntables:
        turntable_id = str(value.get("id", "")).strip().upper()
        connected = tuple(_canonical_block_id(item) for item in value.get("connected_block_ids", value.get("connected", ())) if _canonical_block_id(item))
        if not turntable_id or not connected:
            continue
        aligned = _canonical_block_id(value.get("aligned_block_id")) or None
        address = value.get("address")
        domain_turntables.append(Turntable(turntable_id, str(value.get("name", turntable_id)), connected, aligned, value.get("occupied_by"), _position(value), int(address) if address not in (None, "") else None))

    domain_trains: list[Train] = []
    for value in train_values:
        train_id = _canonical_train_id(value.get("id"))
        if not train_id:
            continue
        mode_value = str(value.get("mode", value.get("class", "manual"))).lower()
        mode = TrainMode.AUTOMATIC if mode_value == "automatic" else TrainMode.STOPPED if mode_value in {"stopped", "safe", "stop"} else TrainMode.MANUAL
        raw_speed = value.get("speed", value.get("speed_kmh", 0))
        speed = max(0.0, float(raw_speed if raw_speed not in (None, "") else 0))
        raw_max_speed = value.get("maxSpeed", value.get("max_speed_kmh", 140))
        max_speed = max(speed, float(raw_max_speed if raw_max_speed not in (None, "") else 140))
        raw_length = value.get("length_mm", 0)
        length_mm = float(raw_length if raw_length not in (None, "") else 0)
        status = TrainStatus.RUNNING if speed > 0 else TrainStatus.STOPPED
        domain_trains.append(
            Train(
                id=train_id,
                name=str(value.get("name", train_id)),
                model=TrainModelInfo(
                    manufacturer=str(value.get("manufacturer", "")),
                    catalogue_number=str(value.get("model_number", "")),
                    prototype=str(value.get("prototype", "")),
                    era=str(value.get("era", "")),
                    decoder_type="Z21 LAN",
                ),
                decoder_address=int(value["address"]) if value.get("address") not in (None, "") else None,
                length_mm=length_mm,
                max_speed_kmh=max_speed,
                mode=mode,
                status=status,
                speed_kmh=min(speed, max_speed),
                current_block_id=_canonical_block_id(value.get("block_id", value.get("position"))) or None,
                destination_block_id=_canonical_block_id(value.get("destination_block_id")) or None,
                consist_ids=tuple(str(item.get("id", item.get("name", "vehicle"))) for item in value.get("consist", ()) if isinstance(item, Mapping)),
                mass_g=float(value.get("mass_g", 0) or 0),
                requested_speed_kmh=0.0 if mode is TrainMode.STOPPED else min(max_speed, float(value.get("requested_speed_kmh", speed))),
            )
        )

    # The compact UI does not have a separate station editor yet.  A station
    # and platform per visible block keeps the persisted model complete and
    # gives the timetable a stable target until those editors are added.
    station_values = [dict(value) for value in stations]
    if station_values:
        domain_stations = tuple(
            Station(
                str(value.get("id", "")).strip(),
                str(value.get("name", value.get("id", "Station"))),
                tuple(_canonical_block_id(item) for item in value.get("block_ids", value.get("blockIds", ()))),
                tuple(str(item) for item in value.get("platform_ids", value.get("platformIds", ()))),
                tuple(str(item).upper() for item in value.get("waypoint_ids", value.get("waypointIds", ()))),
            )
            for value in station_values
            if str(value.get("id", "")).strip()
        )
    else:
        domain_stations = tuple(
            Station(f"station-{block.id.lower()}", block.name or block.id, (block.id,), (f"platform-{block.id.lower()}",))
            for block in domain_blocks
        )
    platform_values = [dict(value) for value in platforms]
    if platform_values:
        domain_platforms = tuple(
            Platform(
                str(value.get("id", "")).strip(),
                str(value.get("name", value.get("id", "Platform"))),
                str(value.get("station_id", value.get("stationId", ""))).strip(),
                _canonical_block_id(value.get("block_id", value.get("blockId"))),
                float(value.get("length_mm", value.get("lengthMm", 0))),
            )
            for value in platform_values
            if str(value.get("id", "")).strip()
        )
    else:
        domain_platforms = tuple(
            Platform(f"platform-{block.id.lower()}", block.name or block.id, f"station-{block.id.lower()}", block.id, block.length_mm)
            for block in domain_blocks
        )
    block_by_train = {train.id: train for train in domain_trains}
    domain_schedules: list[Schedule] = []
    station_id_set = {station.id for station in domain_stations}
    station_ids = {station.name.lower(): station.id for station in domain_stations}
    station_for_block = {
        block_id: station.id
        for station in domain_stations
        for block_id in station.block_ids
    }
    for value in schedules:
        schedule_id = str(value.get("id", "")).strip()
        if not schedule_id or not domain_stations:
            continue
        train_id = _canonical_train_id(value.get("train_id"))
        if train_id not in block_by_train:
            number = str(value.get("number", ""))
            train_id = next((train.id for train in domain_trains if str(train.decoder_address or "") == number), domain_trains[0].id if domain_trains else "")
        if not train_id:
            continue
        block_id = block_by_train[train_id].current_block_id or domain_blocks[0].id
        requested_station = str(value.get("station_id", value.get("stationId", ""))).strip()
        station_id = requested_station if requested_station in station_id_set else station_ids.get(str(value.get("station", "")).lower(), station_for_block.get(block_id, domain_stations[0].id))
        raw_stops = value.get("stops")
        parsed_stops: list[ScheduleStop] = []
        if isinstance(raw_stops, (list, tuple)):
            for raw_stop in raw_stops:
                if not isinstance(raw_stop, Mapping):
                    continue
                parsed_station = str(raw_stop.get("station_id", raw_stop.get("stationId", station_id))).strip()
                if not parsed_station:
                    continue
                parsed_stops.append(
                    ScheduleStop(
                        parsed_station,
                        str(raw_stop.get("platform_id", raw_stop.get("platformId", ""))).strip() or None,
                        _optional_time_seconds(raw_stop.get("arrival_seconds", raw_stop.get("arrivalSeconds"))),
                        _optional_time_seconds(raw_stop.get("departure_seconds", raw_stop.get("departureSeconds"))),
                    )
                )
        if not parsed_stops:
            arrival = _time_seconds(value.get("time", "00:00"))
            parsed_stops = [ScheduleStop(station_id, str(value.get("platform", "")).strip() or f"platform-{block_id.lower()}", arrival, arrival + 60)]
        status_value = str(value.get("state", "planned")).lower()
        status = next((candidate for candidate in ScheduleStatus if candidate.value == status_value), ScheduleStatus.PLANNED)
        domain_schedules.append(
            Schedule(
                schedule_id,
                str(value.get("service", schedule_id)),
                train_id,
                tuple(parsed_stops),
                status,
                bool(value.get("repeat", False)),
                str(value.get("origin", "")),
                str(value.get("destination", "")),
                str(value.get("route", "")),
            )
        )

    domain_scans = tuple(
        PhotoScan(
            str(value.get("id", "")).strip(),
            str(value.get("label", value.get("name", value.get("id", "Scan")))),
            str(value.get("description", "")),
            str(value["image"]) if value.get("image") not in (None, "") else None,
            _anchor(value.get("anchor")),
        )
        for value in (dict(item) for item in scans)
        if str(value.get("id", "")).strip()
    )

    return LayoutSnapshot(
        revision=max(0, int(revision)),
        blocks=tuple(domain_blocks),
        turnouts=tuple(domain_turnouts),
        stations=domain_stations,
        signals=tuple(domain_signals),
        waypoints=tuple(domain_waypoints),
        turntables=tuple(domain_turntables),
        platforms=domain_platforms,
        trains=tuple(domain_trains),
        schedules=tuple(domain_schedules),
        scans=domain_scans,
        connection_limits=tuple(ConnectionSpeedLimit(
            _canonical_block_id(rule.get("from", rule.get("from_block_id"))),
            _canonical_block_id(rule.get("to", rule.get("to_block_id"))),
            rule.get("speed_limit_kmh"),
            tuple((_canonical_train_id(key), value) for key, value in rule.get("train_speed_limits", {}).items()),
        ) for rule in connection_limits),
    )


def snapshot_to_ui(snapshot: LayoutSnapshot) -> dict[str, Any]:
    """Project a domain snapshot back into the dashboard's display shape."""

    blocks = [
        {
            "id": block.id,
            "name": block.name or block.id,
            "x": block.position.x if block.position else 62,
            "y": block.position.y if block.position else 224,
            "length_mm": block.length_mm,
            "status": block.state.value,
            "occupied_by": block.occupied_by,
            "station": block.name or "H0 layout",
            "neighborIds": [item.lower() for item in block.neighbor_ids],
        }
        for block in snapshot.blocks
    ]
    trains = [
        {
            "id": train.id,
            "name": train.name,
            "address": train.decoder_address,
            "mode": train.mode.value,
            "speed": train.speed_kmh,
            "requested_speed_kmh": train.requested_speed_kmh if train.requested_speed_kmh is not None else train.speed_kmh,
            "direction": "forward",
            "block_id": train.current_block_id,
            "length_mm": train.length_mm,
            "manufacturer": train.model.manufacturer,
            "model_number": train.model.catalogue_number,
            "era": train.model.era,
            "decoder_protocol": train.model.decoder_type or "DCC",
            "mass_g": train.mass_g,
            "max_speed_kmh": train.max_speed_kmh,
            "consist": [{"id": item, "name": item, "type": "vehicle"} for item in train.consist_ids],
        }
        for train in snapshot.trains
    ]
    turnouts = [
        {
            "id": turnout.id,
            "name": turnout.name or turnout.id,
            "from": turnout.entry_block_id,
            "to": turnout.straight_block_id,
            "alternate": turnout.diverging_block_id,
            "state": turnout.position.value,
            "address": turnout.address,
        }
        for turnout in snapshot.turnouts
    ]
    signals = [
        {
            "id": signal.id,
            "name": signal.name or signal.id,
            "block_id": signal.block_id,
            "protects_block_id": signal.protects_block_id,
            "aspect": signal.aspect.value,
            "address": signal.address,
        }
        for signal in snapshot.signals
    ]
    waypoints = [
        {
            "id": waypoint.id,
            "name": waypoint.name or waypoint.id,
            "connected_node_ids": list(waypoint.connected_node_ids),
            "x": waypoint.position.x if waypoint.position else 0,
            "y": waypoint.position.y if waypoint.position else 0,
        }
        for waypoint in snapshot.waypoints
    ]
    turntables = [
        {
            "id": turntable.id,
            "name": turntable.name or turntable.id,
            "connected_block_ids": list(turntable.connected_block_ids),
            "aligned_block_id": turntable.aligned_block_id,
            "occupied_by": turntable.occupied_by,
            "x": turntable.position.x if turntable.position else 0,
            "y": turntable.position.y if turntable.position else 0,
            "address": turntable.address,
        }
        for turntable in snapshot.turntables
    ]
    stations = {station.id: station for station in snapshot.stations}
    schedules = []
    for schedule in snapshot.schedules:
        first_stop = schedule.stops[0]
        last_stop = schedule.stops[-1]
        train = next((item for item in snapshot.trains if item.id == schedule.train_id), None)
        first_station = stations.get(first_stop.station_id)
        last_station = stations.get(last_stop.station_id)
        first_seconds = first_stop.arrival_seconds if first_stop.arrival_seconds is not None else first_stop.departure_seconds or 0
        total_minutes = int(first_seconds // 60)
        route = schedule.route_label or f"{schedule.origin or (first_station.name if first_station else first_stop.station_id)}  →  {schedule.destination or (last_station.name if last_station else last_stop.station_id)}"
        schedules.append(
            {
                "id": schedule.id,
                "time": f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}",
                "service": schedule.name,
                "number": str(train.decoder_address if train and train.decoder_address is not None else ""),
                "train_id": _ui_train_id(schedule.train_id),
                "station_id": first_stop.station_id,
                "route": route,
                "origin": schedule.origin,
                "destination": schedule.destination,
                "platform": first_stop.platform_id or "—",
                "repeat": schedule.repeat,
                "stops": [
                    {
                        "station_id": stop.station_id,
                        "platform_id": stop.platform_id,
                        "arrival_seconds": stop.arrival_seconds,
                        "departure_seconds": stop.departure_seconds,
                    }
                    for stop in schedule.stops
                ],
                "state": schedule.status.value.title(),
            }
        )
    platforms = [
        {
            "id": platform.id,
            "name": platform.name,
            "stationId": platform.station_id,
            "blockId": platform.block_id,
            "lengthMm": platform.length_mm,
            "blockIds": [platform.block_id.lower()],
        }
        for platform in snapshot.platforms
    ]
    stations = [
        {
            "id": station.id,
            "name": station.name,
            "blockIds": list(station.block_ids),
            "platformIds": list(station.platform_ids),
            "waypointIds": list(station.waypoint_ids),
        }
        for station in snapshot.stations
    ]
    scans = [
        {
            "id": scan.id,
            "label": scan.label,
            "description": scan.description,
            "image": scan.image,
            "anchor": {"x": scan.anchor.x, "y": scan.anchor.y} if scan.anchor else None,
        }
        for scan in snapshot.scans
    ]
    return {
        "blocks": blocks,
        "trains": trains,
        "turnouts": turnouts,
        "signals": signals,
        "waypoints": waypoints,
        "turntables": turntables,
        "stations": stations,
        "schedules": schedules,
        "platforms": platforms,
        "scans": scans,
        "connection_limits": [{"from": rule.from_block_id, "to": rule.to_block_id,
                               "speed_limit_kmh": rule.speed_limit_kmh,
                               "train_speed_limits": dict(rule.train_speed_limits)}
                              for rule in snapshot.connection_limits],
    }
