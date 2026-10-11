# Computer-connected occupancy detectors

Settings → Hardware blocks → Map hardware blocks → **Computer-connected detectors (USB / network)** configures the computer bridge independently of the driving command station. The computer opens either a serial port (115200 baud by default, 8N1, no flow control) or a TCP client connection to a listening bridge. Occupancy-only setups receive data without sending commands. Optional track-switch assignments enable acknowledged output commands on this same connection; see [switch setup](COMPUTER_TURNOUTS.md).

This is an explicit JSON bridge protocol, not automatic support for every USB, CAN, S88, LocoNet or other vendor detector. Firmware or bridge software must translate its detector protocol into the format below. The native build includes pyserial; source installations need `pip install -r requirements-hardware.txt` for serial input.

Send complete UTF-8 snapshots terminated by a newline:

```json
{"contacts":[{"module":1,"input":1,"occupied":true},{"module":1,"input":2,"occupied":false}]}
```

- Every mapped contact must occur in every snapshot, including clear contacts. Additional contacts are allowed.
- Module and input must be integers from 1 to 65535, with no duplicates. `occupied` must be a JSON boolean.
- Each snapshot contains only `contacts`; each contact contains only `module`, `input`, `occupied`.
- Send full snapshots regularly, including while occupancy stays unchanged; one per second suits the default 3-second timeout.
- Timeout is configurable from 0.5 to 60 seconds. Maximum frame size is 64 KiB; maximum contacts per snapshot is 4096.
- TCP is a trusted local-network stream. Point the app at the bridge's host and listening port (default 5550). It sends no poll requests. Switch commands are sent only when a switch is explicitly assigned to the bridge and operated in physical mode.

Connections and assignments persist in the operating-plan sidecar. Startup never activates the saved connection. Connect explicitly after launching the application. Switching driving stations retains the independent provider and mappings; switching to simulation leaves the detector connection available for preview but never changes simulated occupancy.

Any active contact occupies its block. Physical track snapshots merge station and computer occupancy by union; neither source can clear the other. Missing, malformed, disconnected or timed-out reports protect every computer-mapped block as unknown. Physical positive speed commands are rejected while configured computer feedback is unhealthy, and the next dispatch cycle emergency-stops trains. Fresh reports restore health without automatically resuming trains. Readings never provide train identity.

Physical track power must be off to activate/deactivate the connection or modify active detector mappings. Disconnect before changing connection settings. Several contacts may share a block, but a computer contact cannot map to different blocks. Computer addresses are independent of command-station addresses.

Commands: `configure_computer_feedback` with `config`, `connect_computer_feedback`, `disconnect_computer_feedback`; assignments use `set_block_feedback` with `system: "computer"`. `GET /api/block-feedback?system=computer` returns configuration, connection health, protected occupancy and saved assignments. Detector data enters exclusively through the configured receive stream.

The packaged browser guide is `/computer-feedback.html`. Verify the bridge with physical detectors before operating trains; software tests use TCP and serial fixtures.
