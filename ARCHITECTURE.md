# H0 Z21 Train Controller

This project is a dependency-light Python application intended to run from Visual Studio.
The first iteration is a modular local controller: a simulated track system can be used without
hardware, while the Z21 adapter is kept behind the same interface for later integration.

## Module boundaries

- `backend/core`: domain entities (including editable topology and photo-scan manifests), state store, events, layout controller, layout graph and routing algorithms.
- `backend/services`: scheduler, dispatcher, route updater, movement authority/interlocking, avoidance and connection checks.
- `backend/infrastructure`: simulated track, real Z21 track adapter, Z21 transport and train database.
- `backend/runtime.py`: default dependency-injection composition for a simulation-first controller.
- `backend/api`: local HTTP API, browser/domain anti-corruption bridge and application composition. Typed domain events are projected into the bounded `/api/events` history.
- `frontend`: browser UI served by the local API. It consumes JSON and does not own domain rules; local photo previews stay browser-scoped.
- `tests`: fast unit tests for graph routing, state transitions, simulation and the API.

## Design rules

1. Keep domain logic independent of UI, HTTP and hardware.
2. Depend on protocols/interfaces at integration boundaries.
3. Use immutable-ish dataclasses for snapshots and explicit commands for mutations.
4. Make simulation the default so the application is useful without a Z21 connected.
5. Never send a hardware command without a connection check and a clear command result.
6. Treat route planning as pure graph work; safety/occupancy checks belong in services.
7. Keep browser-shaped state out of the domain layer; translate it at `backend/api/domain_bridge.py`.
8. Treat configured physical feedback as a safety input: a failed poll or connection check forces a dispatcher safe stop.

## First milestone

The local app should open a dashboard with a sample H0 layout, show blocks and trains,
allow a manual speed command, run a deterministic simulation tick, calculate a route with
A* (with BFS as a simple fallback), expose a Z21 connection indicator, and open a photo-scan
viewer even when no scan asset has been configured yet.

## Next extension points

- RailCom-based train identification on top of the anonymous R-BUS occupancy layer.
- Photogrammetry-grade reconstruction, calibration, and occlusion on top of the optional depth/mesh scan surface.
- Train database imports from manufacturer catalogues and a richer browser catalogue picker.
- Hardware-specific accessory feedback and signal/turntable state polling beyond the current command adapter.
- Multi-user layout collaboration and audit history.
- Additional Z21 accessory, booster and programming-track commands.
