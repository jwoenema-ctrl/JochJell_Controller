# Track triggers

On **Automation**, open **Track triggers** and choose **New trigger**.

1. Name the trigger and select its block.
2. Choose any passing train or check the trains it applies to. Optionally filter by forward/reverse decoder direction.
3. Add function actions (on, off, or a pulse of 0.1–60 real seconds) or a saved routine. Functions can target the locomotive or a function-equipped rolling-stock entry in the passing train's consist. Cars with the same DCC address switch together.
4. For hardware, enter the occupancy detector module and input, or use an existing mapping shown beneath the detector fields. Save the trigger.

Definitions persist beside the train database in `operating_plan.json`. Old timetable/routine files remain readable. Edit, disable, enable, and delete triggers from the list. Triggers referencing a block outside the loaded layout remain saved and inactive. Remove a block's triggers before deleting that block; renaming it also updates its triggers. A referenced saved routine cannot be deleted until its trigger references are removed.

## Simulation

A trigger runs on a train's transition into its block, once per entry. Startup, placing a train, and refreshing the browser do not count as passing the section. Actions run in the Python controller even when the Automation page is closed.

## Real occupancy detection

An ordinary occupancy detector reports an occupied section, **not a train's decoder address**. Under **Confirm a train's position**, choose the train, its actual block, and its connected block route in travel order (for example `B01, B02, B03`). The route must include the current block. An empty route field reports only that current block.

After a known clear-to-occupied change, the controller uses known positions and the planned routes of moving trains to infer one passing train. It tracks these inferred entries privately through all mapped sections; this does not replace protected sensor occupancy or relax dispatch interlocking. Keep position reports and planned routes accurate, including after manually relocating a train. If more than one train could have entered, or no moving train can be identified, actions are skipped and the trigger shows why. Confirming that pending occupied section identifies the passing train and runs its applicable triggers once. The pending entry is discarded when the section clears.

Hardware occupancy is observed at the controller's polling interval (currently one second), so choose a section that stays occupied long enough for detection. A section already occupied at startup, after editing mappings, or after feedback/power recovery is not a new entry: it must clear before it can trigger. Multiple contacts mapped to one block act as one occupied section.

Detector module/input identifiers follow the active adapter: Z21 family/DR5000 use R-Bus module/input, ECoS uses feedback module/contact, Märklin uses feedback device/contact, and XpressNet uses feedback module/input. Adapter limits are checked when saving. Hardware switching keeps definitions, but incompatible detector mappings stay inactive. Switch track power off before adding, changing or removing detector mappings. Deleting the last trigger that owns a contact also removes that contact mapping; an independently configured mapping remains.

## Actions and conflicts

Function pulses use wall-clock seconds independently of the accelerated world clock and browser refresh. A later command to the same decoder function replaces a pending pulse. Controller shutdown, power off, hardware switching and loss of feedback cancel active pulses and attempt to turn their functions off. Changes to decoder addresses or consists also end pulses before modifying their targets.

Saved routines are recompiled for the passing train's speed limits. They use the existing routine runner and stop the train when complete. A trigger cannot replace an already running routine, calibration or coordinate movement, or override a train stopped for safety. Function and routine actions are issued in list order; starting a routine schedules its actions asynchronously. A failed action is reported in the trigger status and stops the remaining actions for that entry; actions already sent are not rolled back. Separate trains can run separate routines.

No physical command station or occupancy detector has been used to verify this feature yet.
