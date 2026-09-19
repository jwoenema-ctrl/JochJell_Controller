# H0 Z21 Train Controller

Modular Python controller and browser dashboard for an H0 model railway using the Roco/Z21 LAN interface.

## Personalized controls

- In Settings, use **Panel arrangement** to reorder each page's panels or move
  the control panels to the right. Save the arrangement to retain it after restart.
- Double-click a graph block to open its editor. Train profiles open on **Data sheet**.
- The speed dial applies its last chosen value automatically. Changing train,
  stopping or switching control mode cancels a queued dial change; direction
  remains locked until the train has stopped.
- Connection speed restrictions support a default limit and individual train
  overrides. See [connection limits and motion](docs/CONNECTION_SPEED_LIMITS.md).
- The HTTP controller owns a single motion clock, independent of open windows.
  Graph markers interpolate simulation positions; physical positions are not
  invented when feedback cannot locate a train within a block.
- The supplied [transparent logo](docs/LOGO.md) is used by the interface and executables.
- The Trains workspace includes a bounded 10 km/h / 100 ms calibration workflow.
  Measurements are stored per locomotive and are required before coordinate-target
  planning from the 2D pinboard.
- The Automation workspace includes the node graph, 2D pinboard and timetable.
  Pinboard drops validate direction, topology, occupancy and calibration before
  storing a target; execution is a separate confirmed action and always has a
  bounded stop timer, including on the native app.
- **Ping saved DCC IDs** scans all saved locomotives and reports detected, unknown
  and error results using available track feedback.
- The Trains workspace includes persistent rolling-stock quantities, a guarded
  DCC CV read/write panel, and an Automation action recorder for speed, direction,
  and decoder-function actions.

## Run locally

### Windows executable

For the all-in-one app-window edition, use `dist/H0-Control-Desk-Native.exe`.
It embeds the complete interface using [pywebview](https://pywebview.flowrl.com/guide/usage.html)
and Microsoft WebView2: no external browser or separate controller window opens.
It starts in simulation; use **Settings → Connection → Connect to real Z21** for an
explicitly confirmed connection. The Controller menu retains Stop and exit only.
Switching saves the current layout after stopping trains and switching power off.
It shares the desktop launcher's AppData, so close the
other edition first. Microsoft Edge WebView2 Runtime is required on the destination PC.
Build with `python -m pip install -r requirements-native.txt` followed by
`./scripts/build_native_windows.ps1`. See [embedded edition notes](docs/WINDOWS_NATIVE.txt).

When using the Roco 10814 WLAN Package, first complete the one-time z21start unlock
and connect Windows to the Z21 router yourself. In **Settings → Connection**, select
**Use Roco 10814 WLAN**, save the settings, and then choose **Connect via WLAN**.
That explicit action connects to the real Z21 after checking that Windows routes its
address through an active wireless adapter. The checkbox does not join Wi-Fi or
connect to hardware by itself. The app never asks for or stores the WLAN password;
use the password printed on the router label in Windows. See the
[10814 WLAN setup guide](docs/WLAN_10814.md).

The original browser-launcher edition is still available:

Run `dist/H0-Control-Desk.exe`, choose Simulation, and click **Start controller**.
The self-contained Windows x64 executable includes Python, the backend, and frontend assets;
Visual Studio and Python are not required on the destination PC. A small desktop controller
window opens the interface in your default browser. Keep that window open while operating;
**Stop controller and exit** stops the controller and requests track power off.

App data is stored separately in `%LOCALAPPDATA%/H0 Control Desk/`, not inside the executable.
Existing development data is not bundled or overwritten. To transfer it, close both controllers
and copy your `controller.sqlite3` and `scans` folder into that app-data directory, backing up
any existing destination files first. Only one desktop controller can use port 8765 at a time.
Physical Z21 control must be selected explicitly in the launcher and confirmed; it uses the
IP address saved in Settings. This build is unsigned and has no installer or automatic updater.

Build it on Windows using the [PyInstaller packaging tools](https://www.pyinstaller.org/en/stable/usage.html):

```powershell
python -m pip install -r requirements-build.txt
./scripts/build_windows.ps1
```

For downloads intended for other computers, prefer the assets on the repository's
GitHub Releases page over temporary workflow artifacts. A pushed tag matching `v*`
builds and tests the app, then publishes `H0-Control-Desk-Native.exe` and
`H0-Control-Desk-Native-Windows-x64.zip` as release assets, together with
`SHA256SUMS.txt` for integrity checking. Ordinary pushes and manual workflow runs
build test artifacts but do not publish a release. A version tag is release-once:
the workflow fails instead of replacing assets if a release already exists for it.

The selected-train panel includes Forward / Reverse. Direction changes require a stationary
train under manual or stopped control; they never start the train. Z21 direction is sent in a
zero-speed DCC packet, and later speed commands retain that direction. In simulation, reverse
traverses the configured route backwards; it does not create a new route. Direction is live
controller state, not a persisted train preference, and new controller sessions start forward.

### From source

From the repository root:

```powershell
python "Train Controller/Train_Controller.py"
```

The app starts in simulation mode by default and serves the dashboard at `http://127.0.0.1:8080`.

Run the standard-library smoke tests with:

```powershell
python -m unittest discover -s tests
```

The interface has separate Dispatch, Layout editor, Trains, Timetable, 3D scans, and Settings
pages, with light, dark, and device-following themes. The viewer uses a bounded viewport,
including on phones; Settings previews your theme and saves preferences explicitly.

Frontend regression checks (optional development dependencies only):

```powershell
node --test tests/js/scan_viewer.test.js
npm install --no-save --no-package-lock playwright@1.62.1
npx playwright install chromium
node tests/browser_smoke.cjs
```

The browser suite creates disposable controller data and never enables physical Z21 control.
It verifies settings validation and persistence across restart, image uploads, viewer resize
stability, page navigation, both themes, and mobile overflow. Set `PYTHON` to your Python
executable if needed, `BROWSER_CHANNEL=chrome` to use an installed Chrome, and `SCREENSHOT_DIR`
to save screenshots. These checks also run in GitHub Actions.

The project deliberately has no third-party runtime dependencies in the first milestone. The simulated track system is the default; real Z21 communication is isolated behind the infrastructure adapter and must be enabled explicitly after validating the network address and hardware setup.

For a physical Z21, set `H0_Z21_HOST` (and optionally `H0_Z21_PORT`) before launch. R-BUS contact
mapping can be supplied as `H0_Z21_FEEDBACK_MAP=1:1=B01,1:2=B02`. See
[Z21_INTEGRATION.md](docs/Z21_INTEGRATION.md) for the safety boundary and wiring assumptions.

### Settings and explicit physical startup

The Settings page saves appearance, Z21 IPv4 address/UDP port, WLAN-path preference, browser
refresh frequency, and route-planning intervals in the controller database. Saving connection
settings never connects to hardware or changes the active endpoint. The WLAN preference contains
no SSID or password. To use the saved address on the next physical startup from source:

```powershell
$env:H0_TRACK_SYSTEM = "z21"
python "Train Controller/Train_Controller.py"
```

`H0_Z21_HOST` and `H0_Z21_PORT`, when set, override the saved address and port. Setting
`H0_Z21_HOST` also explicitly selects physical mode for compatibility with earlier launches.
For simulation, use `H0_TRACK_SYSTEM=simulation` (or leave it unset) and leave `H0_Z21_HOST`
unset. Changes to an active physical endpoint require a restart. The settings response shows
the active endpoint, effective next endpoint, environment-override status, and whether a restart
is needed. In packaged editions, physical operation still requires the explicit
**Connect to real Z21** action and confirmation after saving settings.

Adaptive planning uses the busy interval while trains are moving or a schedule is active, and
the idle interval otherwise (including paused simulation or track power off). With adaptive mode
off, the busy interval is the fixed interval. Planning intervals accept 250–60000 ms; browser
refresh accepts 1000–60000 ms. The background planner only recalculates routes and reservations:
it does not advance simulation, dispatch trains, poll hardware, or send movement commands.
Layout edits force an immediate planning refresh, while explicit dispatch ticks retain their
independent safety checks. `GET /api/settings` exposes the live planning cadence and refresh count;
`POST /api/settings` accepts a partial flat settings object or an object nested under `settings`.

Photo uploads from Settings or the 3D viewer accept PNG, JPEG, and WebP up to 10 MiB, 10000 pixels
per side, and 36 megapixels. `POST /api/scans/upload` accepts `filename`, `label`, `mime_type`, and
base64 `data`, and returns `scan` and `scans`. Generated image files live in the database's sibling
`scans` directory (normally `data/scans`); their manifest is saved with the current layout and
survives restart. Uploaded files are served through validated `/api/scans/files/...` URLs.
Uploading a photograph supplies an image surface for the viewer, not automatic photogrammetry
or a reconstructed 3D mesh.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module boundaries and extension points.

The dashboard includes a local photo-scan manifest and dependency-free WebGL perspective viewer
with optional depth-map/mesh support and a 2D fallback. Add
scan image URLs using the schema in [PHOTO_SCAN_VIEWER.md](docs/PHOTO_SCAN_VIEWER.md), or place
controller-relative images under `data/scans/` and link them as `/scans/filename.jpg`. Layouts can
be persisted as complete domain snapshots with [LAYOUT_PERSISTENCE.md](docs/LAYOUT_PERSISTENCE.md).
The runnable app stores them in `data/controller.sqlite3`; set `H0_CONTROLLER_DB=:memory:` for a
disposable session.

Train model details can be exported in the portable catalogue format from `GET /api/train-catalogue`
or as CSV with `GET /api/train-catalogue?format=csv`. The format includes decoder functions,
maintenance history and ordered rolling stock, so the database is not tied to one installation.
The train data sheet also imports JSON/CSV catalogues with explicit error, skip or replace conflict
handling.
