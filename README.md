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

The project deliberately has no third-party runtime dependencies in the first milestone. The simulated track system is the default; real Z21 communication is isolated behind the infrastructure adapter and must be enabled explicitly after validating the network address and hardware setup.

For a physical Z21, set `H0_Z21_HOST` (and optionally `H0_Z21_PORT`) before launch. R-BUS contact
mapping can be supplied as `H0_Z21_FEEDBACK_MAP=1:1=B01,1:2=B02`. See
[Z21_INTEGRATION.md](docs/Z21_INTEGRATION.md) for the safety boundary and wiring assumptions.

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
