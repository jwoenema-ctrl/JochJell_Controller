# Layout persistence

`SQLiteLayoutRepository` stores complete `LayoutSnapshot` values as validated JSON in SQLite.
It preserves the core model boundary: the editor works with immutable domain objects, while the
repository owns storage and schema setup.

The repository supports:

- blocks, turnouts, stations, signals, waypoints, turntables and platforms;
- train model/decoder data and consist references;
- schedules and their station stops;
- editable block connections and photo-scan manifest references/anchors;
- revision numbers, named layouts, listing, replacement and deletion.

The local application composes this repository into `ControllerRuntime`. The dashboard's layout
editor therefore saves through the same immutable snapshot and graph model used by routing and
dispatching. The HTTP surface is:

- `GET /api/layouts` to list saved layout metadata;
- `POST /api/layouts` with `{ "layout_id": "yard", "name": "West yard" }` to save the current editor state;
- `GET /api/layouts/{layout_id}` to load a saved layout projection;
- the `save_layout` command for the same operation from the browser editor.

The runnable app uses `data/controller.sqlite3` by default (override with `H0_CONTROLLER_DB`).
Tests and embedded applications can still use `:memory:`.
