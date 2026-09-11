# H0 controller feature map

The project is intentionally split by replacement boundary so a simulated layout can be iterated
without changing the Z21 protocol adapter.

| Area | Current implementation |
| --- | --- |
| Layout domain | Blocks, turnouts, stations, signals, waypoints, turntables and platforms in `backend/core/models.py` |
| State and events | Versioned snapshots, subscriptions and typed events in `backend/core/state.py` and `backend/core/events.py` |
| Routing | Layout graph plus deterministic A* and BFS in `backend/core/graph.py`, `backend/core/routing.py` |
| Dispatching | Manual/automatic arbitration, route reservations, movement authority, turnout interlocking and avoidance stops in `backend/services/` |
| Timetable | Deterministic scheduler, API commands and schedule simulation events |
| Track I/O | Fixed-step simulator, connection-gated Z21 LAN commands, track power and R-BUS feedback polling in `backend/infrastructure/` |
| Persistence | SQLite layout snapshots plus train model, decoder-function, maintenance and ordered rolling-stock records; portable JSON/CSV train catalogue export |
| Browser UI | Graph editor with persisted block connections, topology-aware systematic view, signal/turnout/turntable controls, layout-asset inspector, timetable/service editor, per-train mode switcher, train profile/consist/database-record editor, JSON/CSV catalogue import/export and WebGL photo-scan depth/mesh surface with 2D fallback |
| Visual Studio | `Train Controller/Train Controller.pyproj` includes backend, frontend, docs and tests |
| GitHub checks | `.github/workflows/test.yml` runs the Python suite and frontend syntax checks on pushes and pull requests |

## Hardware activation

Simulation is the default. Set `H0_Z21_HOST` and optionally `H0_Z21_PORT` before starting the
Visual Studio entry point to select the physical adapter. Commands remain blocked until the Z21
version check succeeds. A real layout still needs the user's block feedback hardware and DCC
address mapping before automatic driving is safe.

## Photo scans

The viewer accepts scan entries with an optional image and one or more anchors in the API manifest.
The current sample uses a no-image placeholder because no user photo scan has been supplied yet;
adding the image path/URL is a data change, not a renderer rewrite. The current renderer is a
optional depth maps and triangulated mesh grids for a genuine perspective/depth surface. It is not yet a photogrammetry-grade reconstruction pipeline with camera calibration, dense geometry inference, or occlusion solving.
