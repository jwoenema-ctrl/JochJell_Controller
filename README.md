# H0 Z21 Train Controller

Modular Python controller and browser dashboard for an H0 model railway using the Roco/Z21 LAN interface.

## Run locally

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

The Settings page saves appearance, Z21 IPv4 address/UDP port, browser refresh frequency, and
route-planning intervals in the controller database. Saving an address never connects to hardware
or changes the active endpoint. To use the saved address on the next physical startup:

```powershell
$env:H0_TRACK_SYSTEM = "z21"
python "Train Controller/Train_Controller.py"
```

`H0_Z21_HOST` and `H0_Z21_PORT`, when set, override the saved address and port. Setting
`H0_Z21_HOST` also explicitly selects physical mode for compatibility with earlier launches.
For simulation, use `H0_TRACK_SYSTEM=simulation` (or leave it unset) and leave `H0_Z21_HOST`
unset. Changes to an active physical endpoint require a restart. The settings response shows
the active endpoint, effective next endpoint, environment-override status, and whether a restart
is needed; there is deliberately no browser-side switch that activates physical operation.

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
