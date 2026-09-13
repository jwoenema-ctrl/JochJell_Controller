# Directed connection limits and train motion API

`POST /api/commands` accepts:

```json
{"type":"set_connection_speed_limit","from":"b01","to":"b02","speed_limit_kmh":40}
```

Add `train_id` to edit that train's override instead of the default. A null
override removes it (inherits the default). A null default means unrestricted.
An optional `train_speed_limits` object replaces all overrides; keys accept
canonical or UI train IDs. Limits must be finite non-negative numbers; zero
holds the train. Overrides replace the default, but never exceed the train's
maximum speed. Reverse connections have independent rules.

`state.layout.connections` lists every directed connection, with lowercase
`from`, `to`, nullable `speed_limit_kmh`, and a `train_speed_limits` object keyed
by UI train ID. `state.layout.connection_limits` contains configured rules.
Use normal Save layout to persist rules in the layout snapshot. Rules survive
load, restart and block renaming; disconnect removes both directions' rules.

Every train has `requested_speed_kmh`, `effective_speed_kmh`,
`actual_speed_kmh` (null on physical track), and `speed_limit_kmh`.
Its `motion` object contains:

- `block_id`, `route`, `from_block_id`, `to_block_id`: lowercase IDs.
- `position`: normalized progress 0..1 along the outgoing connection; null on
  physical track. A terminal block has null `to_block_id`.
- `speed`, `effective_speed`, `requested_speed`: normalized 0..1; `speed` is
  null when real speed has not been measured.
- `direction`: +1 or -1 through the ordered route.
- `time_seconds`, `tick_seconds`, `source` (simulation/reported/unknown).

The limit applies from departure/source block through entry into its successor.
Simulation clamps motion within each tick, including multiple block transitions;
safety braking, occupancy, power and stop still take precedence. Requested speed
is retained through zones; stopping clears the request and does not auto-restart.

The HTTP server runs ONE backend-owned motion clock (simulation fixed steps,
physical dispatch once per second). Tabs must poll state, NOT run their own tick
loops. `state.motion_clock` reports clock status. Explicit simulation step calls
remain available for deliberate timetable fast-forward; they are not polling.
The seconds/rate request advances seconds times rate (at most 600 seconds per
request), with one timetable minute per 60 simulated seconds. The multiplier
affects the step button, not the live clock. Fast-forward is rejected on hardware.
Directly constructed applications remain deterministic until start_motion_clock.
The separate route-refresh worker remains planning-only.
The displayed simulation clock uses actual track seconds (ten 0.1-second ticks
equal one second). The continuous clock advances the minute-based timetable only
once per elapsed minute. Deliberate explicit step/fast-forward calls retain the
existing timetable-minute stepping contract; `simulation.schedule_minutes` exposes
that separate timetable cursor, including deliberate fast-forwards.

## Physical track position is not invented

R-BUS occupancy does not identify a locomotive or measure in-block position.
Until an identified traversal is supplied, the physical adapter conservatively
uses the smallest applicable configured limit for that train. A trusted operator
or train-identification integration can report:

```json
{"type":"report_train_position","train_id":"t1","block_id":"b02","route":["b01","b02","b03"]}
```

This updates the reported traversal and reapplies its limit to the still-active
request, restoring that request when the new outgoing connection is unrestricted.
Do not treat this endpoint as telemetry; accurate reports are the caller's
responsibility. No physical animation position or measured velocity is fabricated.
Automatic occupancy-only identification and speed calibration are not implemented.
Decoder speed is normalized against configured model maximum; physical km/h is
not measured and requires decoder calibration. Tests use a fake transport, never
live rolling stock.
