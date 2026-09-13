# Layout editing and information

New blocks are numbered by the controller after the largest existing B-number:
B01–B04 produces B05, including after reload. IDs are case-insensitive and stored
uppercase. Custom IDs may contain letters, digits, hyphens and underscores.

Switch track power off before renaming a block ID. The editor updates connected
blocks, train positions, routes, signals, stations, platforms, waypoints,
turntables and live feedback bindings together. Display names can be edited with
power on. Use **Save layout** to persist changes. If you configure feedback mappings
externally through environment variables, update those mappings to the new IDs
before the next launch.

The Layout information panel appears on Dispatch and Layout editor. Train counts
include models assigned to an existing block, not the whole catalogue. Occupied
blocks include controller train positions and available occupancy feedback; unknown
feedback contacts do not identify a train. Stopped trains are listed separately.
Route operations count automatic trains with a non-zero requested speed and an
unfinished route, including those waiting for clearance. Paused simulation or
track power off means no executing operations. Reserved blocks are not route counts.

In physical mode, read-only Z21 system-state requests run at most once every five
seconds during connection polling. Current and voltage are measured; wattage is
an estimate from smoothed current times voltage, not mains power or accumulated
energy. Missing/stale readings and simulation show unavailable, never invented
zero consumption. Without a current Z21 reading the power status is labelled
commanded state.

Protocol reference: [Roco Z21 LAN specification, sections 2.18–2.19](https://www.z21.eu/media/Kwc_Basic_DownloadTag_Component/root-en-main_47-1652-959-downloadTag-download/default/d559b9cf/1628743384/z21-lan-protokoll-en.pdf).
