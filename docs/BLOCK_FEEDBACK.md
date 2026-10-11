# Assign physical track sections to layout blocks

Open **Settings → Connection → Hardware blocks → Map hardware blocks**, or select a block in the graph, open **Edit block**, and choose **Assign hardware detectors**.

1. Choose the detector source that will report occupancy. Assignments are saved separately for each command-station profile, including the individual Z21-family profiles. Choose **Computer-connected detectors** for an independent USB / serial or TCP detector bridge; see [connection setup and reporting format](COMPUTER_FEEDBACK.md).
2. Choose a layout block.
3. Choose **Add input**, then enter the detector's reported **Module** and **Input** addresses. These are feedback addresses, not locomotive DCC addresses.
4. Add more inputs if the block covers several physical detector sections. An occupied input makes the whole logical block occupied; all its inputs must be clear before the detector reports the block clear.
5. Choose **Save assignments**. Assignments persist immediately in `operating_plan.json` beside the controller database; saving the layout is not required to keep the detector assignments themselves.

The editor shows address limits for the selected adapter: R-Bus for Z21-family and DR5000 profiles, ECoS module/contact, Märklin device/contact, or XpressNet module/input. Use the address reported by your command station, which may differ from the label printed on a detector board.

You can prepare assignments in simulation without connecting hardware. On the connected digital system, switch track power off before changing assignments. The controller rejects changes that would remap live feedback while power is on. Editing an inactive profile does not change the connected adapter's mapping.

An input can map to only one logical block per digital system. Conflicting assignments are rejected together; no part of the attempted save is applied. Remove an input row and save to remove that independent assignment, or remove all rows to clear the block's independent assignments.

**All assignments for this digital system** lists the configured contacts. Track-trigger and startup/environment mappings remain visible and cannot be removed through the independent block editor. Edit the owning trigger or startup configuration to remove those mappings. A trigger may share an independent assignment to the same block; removing the trigger preserves the independent mapping, and removing the independent mapping preserves the trigger's mapping.

Renaming a block updates its saved detector references. Remove its saved assignments before deleting the block. Saved mappings whose block is absent from a loaded layout remain stored and inactive; select the missing block in the editor to remove its independent assignments.

Physical occupancy tells the controller whether a track section is occupied. It does not by itself identify a locomotive's decoder address. Train identity, route planning, and [track-trigger detection](TRACK_TRIGGERS.md) continue to use the existing position and feedback safeguards.

The mapping interface and adapter behavior are verified with simulated protocol peers. Physical detector verification is still required for your layout and command station.
