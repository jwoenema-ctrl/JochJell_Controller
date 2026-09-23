# JochJell Controller

JochJell Controller is a local control desk for an H0 model railway. It combines a browser dashboard with a Python controller for train driving, route planning, automation routines, timetables, layout management and Roco/Z21 LAN control.

The application starts in simulation mode. You can build and test a railway plan without connecting hardware, then explicitly switch to a real Z21 connection when the layout and safety checks are ready.

## Download the standalone Windows release

Download the latest files from the [GitHub Releases page](https://github.com/jwoenema-ctrl/JochJell_Controller/releases):

- `JochJell-Controller-Native.exe` — the recommended all-in-one desktop window.
- `JochJell-Controller-Native-Windows-x64.zip` — the same application with supporting notes included.
- `SHA256SUMS.txt` — checksums for verifying downloaded files.

The native edition embeds the dashboard and does not require Python, a web server or a separate browser window. Microsoft Edge WebView2 Runtime is required on the destination PC. The executable is currently unsigned, so Windows SmartScreen may require an explicit confirmation.

### First launch

1. Download the native executable or ZIP from Releases.
2. Extract the ZIP if necessary.
3. Start `JochJell-Controller-Native.exe`.
4. Leave the controller in **Simulation** mode for the first setup.
5. Use the top navigation to configure trains, blocks, routines and schedules.

The browser-launcher executable, `JochJell-Controller.exe`, is also available in build artifacts. It starts a local controller and opens the dashboard in your default browser. Keep its desktop controller window open while using it.

## What the product does

JochJell Controller is organized around four layers:

1. **Fleet** — train profiles, DCC addresses, functions, consists and rolling stock.
2. **Layout** — blocks, turnouts, stations, platforms, signals, waypoints and routes.
3. **Operations** — manual driving, automatic control, routines and timetables.
4. **Connection** — simulation or an explicitly selected physical Roco/Z21 transport.

The selected train's controls are independent from the rest of the fleet. A train can be manual, automatic or stopped without changing the control mode of other trains.

## Main workspaces

### Home — dispatch and live railway view

Home is the operating screen. It includes:

- live train status, position, block and speed;
- the 2D node graph with block occupancy and route reservations;
- selected-train controls for speed, direction, stop and decoder functions;
- track power and simulation controls;
- timetable and dispatcher status;
- route and block activity;
- the 3D/photo-scan viewer when a layout scan is available.

Use **Forward** or **Reverse** only when the train is stationary. A direction change does not start the train. **Stop** is the safe way to cancel motion.

### Trains — fleet and train profiles

The Trains workspace manages the fleet:

- add, edit and remove trains;
- assign and update DCC addresses;
- select a train-specific manual, automatic or stopped mode;
- set maximum speed and train data-sheet details;
- assign decoder functions F0–F31 with names and momentary behavior;
- pair locomotives and manage consist members;
- add or remove rolling stock from a consist;
- maintain rolling-stock quantities and search the catalogue;
- import and export train catalogues as JSON or CSV;
- view maintenance history and decoder data.

**Ping saved DCC IDs** checks saved locomotives through RailCom when supported. A command-station locomotive-info response is shown as context, but is not treated as physical presence by itself.

### Automation — build reusable routes and routines

Automation contains the route editor, routine builder, recorder and pinboard.

#### Train routines

Create a routine for a selected train, then save it for later use. Available action blocks include:

- **Drive** — set a speed and hold it for a duration;
- **Speed staircase** — move from a start speed to an end speed over a chosen duration;
- **Travel distance** — move a calibrated distance at a selected speed;
- **Wait** — pause before the next action;
- **Direction** — set forward or reverse;
- **Function** — switch lighting, horn or another decoder function F0–F31;
- **Stop** — set the train speed to zero.

The Travel distance block uses the selected train's motion calibration. For example, after calibrating the train, a routine can request “travel 20 cm at 30 km/h” and calculate the required movement time from that measurement.

You can record live speed, direction and function commands, then import the last recording into a reusable routine. Playing a routine requires confirmation and ends with a stop command.

#### Route flows

A route is a reusable sequence that can contain:

- track nodes for block-to-block movement;
- saved routines for movement and actions;
- locomotive synchronization blocks for consists.

Use the route dropdowns to find blocks, routines and locomotives when the catalogue becomes large. The Add controls stay inside the editor field so they remain usable on smaller screens.

There are two dispatch styles:

- **Connected-block dispatch** — reserves and traverses connected blocks using the route planner.
- **One-block mode** — intended for a train treated as being on one logical block. Block-to-block reservations are disabled, while scheduled route routines execute directly at departure time.

Select the behavior in **Settings → Operations → Connected-block dispatch**. In one-block mode, a route needs a saved routine block to create movement. A path containing only track nodes has no speed instruction and cannot move a train by itself.

#### Pinboard and layout viewer

The 2D pinboard lets you place trains and rolling stock on a track coordinate or drag a train marker to a calibrated destination. The planner checks direction, topology, occupancy and calibration before accepting a target. Execution is a separate confirmed action with a bounded stop timer.

The photo-scan viewer displays uploaded PNG, JPEG or WebP layout photographs on a 3D surface. It supports orbit, zoom and scan anchors; it does not automatically reconstruct a full 3D railway from photographs.

### Timetable — schedules and dispatcher services

Create a service with:

- departure time;
- service name and train number;
- assigned train;
- station and optional platform;
- display route text;
- dispatch plan.

The dispatch plan can be:

- **Saved route** — bind a reusable route when the service departs;
- **Destination coordinate** — use a calibrated pinboard destination;
- **Timetable only** — display the service without issuing movement.

The simulation world clock advances faster than real time. One real second advances one model minute, so a 24-hour model day lasts 24 real minutes. Timetable events repeat after the clock returns to `00:00`; scheduled departures are not one-shot events.

### Settings — connection, operation and workspace preferences

Settings includes:

- light, dark or device-following theme;
- compact or comfortable interface density;
- browser refresh interval;
- simulation rate and motion preferences;
- Z21 IPv4 address and UDP port;
- Roco 10814 WLAN preference;
- adaptive route-planning intervals;
- connected-block or one-block dispatch;
- photo-scan upload and management;
- per-page panel ordering and sidebar placement.

Saving a Z21 address does not connect to hardware. Physical operation requires an explicit connection action and confirmation.

## A practical first-time tutorial

### 1. Start safely in simulation

Launch the native executable and confirm that the connection indicator says **Simulation**. Keep track power enabled for simulation, but do not select the physical Z21 option until the layout is configured.

### 2. Configure a train

Open **Trains** and select an existing train or choose **Add train**. Enter its name, maximum speed and DCC address. Remove obsolete fleet entries with **Remove train**. Select the train in the selected-train panel and choose **Manual** while testing direct controls.

### 3. Calibrate motion

In the Trains workspace, open calibration for the selected locomotive:

1. Enter a known measurement distance.
2. Start the bounded calibration run.
3. Measure the distance the train actually travelled.
4. Store the measurement.

The result is stored per locomotive. It is required for accurate coordinate targets and Travel distance routine blocks.

### 4. Create a routine

Open **Automation**, select a train and enter a routine name. Add blocks such as:

1. Direction — Forward.
2. Speed staircase — start at 0 km/h, end at 30 km/h, duration 5 seconds.
3. Travel distance — 20 cm at 30 km/h.
4. Wait — 2 seconds.
5. Function — turn the headlight on.
6. Stop.

Save the routine. It is now available in the route-flow catalogue and is written to the operating-plan file.

### 5. Create a route

Open the route editor in **Automation**, choose **New route**, give it an ID and name, then add track nodes or saved routines to the flow. Save the route. For connected-block dispatch, add the block path. For one-block operation, add the routine that should run at departure.

### 6. Create a timetable service

Open **Timetable** and choose **New service**. Assign the train and time, choose **Saved route**, select the route, then save the service. Put the train in **Automatic** mode when the dispatcher should control it. A train in Manual mode waits safely for its own mode to be changed to Automatic.

### 7. Test the service

Set the simulation clock before the departure time, start or resume simulation, and watch the Home dispatch view. At departure you should see the schedule event, route binding and routine movement. If the service is display-only, it will not issue a movement command.

## Persistence and backup

The native application stores data in:

`%LOCALAPPDATA%\JochJell Controller\`

Important files are:

- `controller.sqlite3` — layout, fleet, settings and other controller data;
- `operating_plan.json` — timetable services and saved automation routines;
- `scans\` — uploaded layout photographs.

Timetable and routine edits autosave to `operating_plan.json`; a separate layout save is not required. The file is plain JSON and can be backed up or inspected while the controller is closed. Close the application before copying data, and back up the destination before replacing it.

Routes and physical layout entities are stored in the layout database. Use the application's layout save function when transferring block, station, platform, signal, turnout or route-editor changes.

## Connecting a real Roco/Z21 system

Simulation is the default and is recommended for initial setup. For a physical railway:

1. Configure and test the layout in simulation.
2. Connect Windows to the Z21 network yourself.
3. For the Roco 10814 WLAN package, complete the one-time z21start unlock first.
4. Open **Settings → Connection** and enter the Z21 IPv4 address and UDP port.
5. Enable **Use Roco 10814 WLAN** only when that network path is correct.
6. Choose **Connect to real Z21** and confirm the action.
7. Verify track power, train address and direction with one stationary train.

The application does not join Wi-Fi; it never asks for or stores the WLAN password. The usual 10814 address is `192.168.0.111`, unless your network uses another address. See [WLAN_10814.md](docs/WLAN_10814.md) and [Z21_INTEGRATION.md](docs/Z21_INTEGRATION.md) for hardware details and safety assumptions.

Physical movement still requires explicit track power and dispatcher control. If feedback cannot locate a train within a block, the application reports block-level position and does not invent an exact position.

## Troubleshooting

### A timetable changes state but the train does not move

- Confirm the service uses **Saved route** or **Destination coordinate**, not **Timetable only**.
- Confirm the assigned train is in **Automatic** mode.
- Confirm track power is enabled.
- In one-block mode, confirm the route contains a saved routine block. Node-only paths do not contain movement instructions.
- Check the Home event log for a missing routine, invalid train, missing calibration or unknown layout reference.

### A Travel distance block is unavailable or fails validation

Run and store motion calibration for that specific train first. Calibration is per locomotive; a measurement from another train is not substituted.

### A route cannot be found in the timetable editor

Save the route in the route editor first, then reopen the timetable editor. Use the route dropdown rather than entering a display label manually.

### The physical connection is unavailable

Start in simulation and verify the address and port. Check that Windows is connected to the correct Z21 network, then make the explicit physical connection from Settings. The controller does not join the network automatically.

### The application is already in use

Only one desktop controller may use the AppData directory and local controller port at a time. Close the other JochJell Controller window before starting another edition.

## Run from source

The project has no third-party runtime dependency in its first milestone. From the repository root:

```powershell
python "Train Controller/Train_Controller.py"
```

The source launcher starts in simulation and serves the dashboard at `http://127.0.0.1:8080`.

For an explicit physical startup from source:

```powershell
$env:H0_TRACK_SYSTEM = "z21"
python "Train Controller/Train_Controller.py"
```

`H0_Z21_HOST` and `H0_Z21_PORT` override the saved address and port. R-BUS feedback mapping can be supplied with, for example, `H0_Z21_FEEDBACK_MAP=1:1=B01,1:2=B02`.

## Build and test

Build the browser-launcher Windows executable:

```powershell
python -m pip install -r requirements-build.txt
./scripts/build_windows.ps1
```

Build the recommended native edition:

```powershell
python -m pip install -r requirements-native.txt
./scripts/build_native_windows.ps1
```

Run the complete automated suite:

```powershell
python -m pytest -q
```

Optional frontend checks:

```powershell
node --test tests/js/scan_viewer.test.js
npm install --no-save --no-package-lock playwright@1.62.1
npx playwright install chromium
node tests/browser_smoke.cjs
```

The browser suite uses disposable data and never enables physical Z21 control. GitHub Actions runs the test suite and Windows executable smoke tests for release tags.

## Project documentation

- [Architecture](ARCHITECTURE.md) — module boundaries and extension points.
- [Layout persistence](docs/LAYOUT_PERSISTENCE.md) — saved layout model.
- [Connection speed limits](docs/CONNECTION_SPEED_LIMITS.md) — default and train-specific limits.
- [Z21 integration](docs/Z21_INTEGRATION.md) — transport and safety boundary.
- [Roco 10814 WLAN setup](docs/WLAN_10814.md) — network preparation.
- [Native Windows edition](docs/WINDOWS_NATIVE.txt) — embedded app notes.
- [Photo-scan viewer](docs/PHOTO_SCAN_VIEWER.md) — scan manifest and viewer data.
- [Logo](docs/LOGO.md) — supplied transparent product logo.
