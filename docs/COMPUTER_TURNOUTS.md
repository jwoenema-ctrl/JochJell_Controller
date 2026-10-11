# Computer-connected track switches

Open **Settings → Track switches → Map track switches**. Choose a turnout and either **Command station** (the existing accessory address) or **Computer USB / network bridge**. Computer outputs use module/output integers 1–65535, a pulse duration of 50–1000 ms, and optional inversion of straight/diverging. Each computer output belongs to one turnout. Assignments persist immediately in the operating-plan sidecar; no layout save is needed. Remove a switch's bridge assignment before deleting it.

The connection is shared with [computer occupancy detectors](COMPUTER_FEEDBACK.md), so one USB / serial port or TCP connection can handle inputs and outputs. The mapping screen opens those connection settings. It works independently of the driving command station. Startup leaves the saved connection inactive; connecting or saving never sends an output command. Switches using Command station retain their existing accessory addressing.

Physical track power must be off before changing connections or assignments. Stop and release train routes that lock a turnout before moving or remapping it. **Set straight / Set diverging** and the normal graph control use the selected source. Simulation updates its digital state only, even if the bridge is connected.

The bridge must implement the JSON protocol; arbitrary vendor devices require compatible firmware, bridge software, or a dedicated adapter. The app sends one UTF-8 JSON line terminated by a newline:

```json
{"type":"set_turnout","request_id":"unique-id","module":2,"output":3,"position":"diverging","pulse_ms":250}
```

The bridge owns output timing: it must limit the pulse to the requested duration even if the connection is lost. For a servo/controller, interpret the position safely according to its hardware design. Never rely on a later app packet to release a coil.

Respond on the same stream with:

```json
{"type":"turnout_ack","request_id":"unique-id","module":2,"output":3,"position":"diverging","accepted":true}
```

The request ID, module, output and position must match exactly; `accepted` must be a JSON boolean. Rejection uses `accepted:false` with optional `detail`. Inverted wiring swaps the wire position; the UI retains the logical requested position. An acknowledgement confirms an accepted command, not measured blade position.

Acknowledgements time out after the configured reading timeout, capped at 3 seconds. Wrong, incomplete, unknown and late acknowledgements never confirm a switch. Failed commands are never automatically retried. A negative acknowledgement, timeout or disconnect retains the previous digital state and leaves the hardware command unconfirmed. Physical positive-speed commands are rejected and dispatch stops trains while any configured computer switch is unconfirmed. Set each mapped switch after connecting to establish confirmation; a later explicit accepted command can recover a failed switch.

Keep streaming full occupancy snapshots periodically. A switch-only bridge sends `{"contacts":[]}` every second as its heartbeat. Stale heartbeat also blocks physical movement. Occupancy snapshots and turnout acknowledgements can be interleaved, and acknowledgements never refresh occupancy freshness. Both detector and switch confirmations must be healthy before driving trains.

API: `set_turnout_connector` takes `turnout_id` and `assignment` (`module`, `output`, `pulse_ms`, `inverted`); `assignment:null` restores Command station. `GET /api/turnout-connectors` returns assignments, bridge status and selectable turnouts. `set_turnout` uses the existing route lock and dispatches through the selected connector. The packaged connection guide is `/computer-feedback.html`.

Software validation uses a real TCP fixture and a serial peer fixture. Verify physical output wiring, bounded pulses and switch direction before operating trains.
