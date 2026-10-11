# Track blocks in the train visualizer

The train visualizer draws blocks as coloured track sections. One block can own
several sections on the same connection, on parallel tracks, or through a junction.
All its sections share its colour and the occupancy/reservation reported for that
block. Orange outlines mean occupied; dashed violet outlines mean reserved. The
centre line keeps the block colour in either state.

## Assign tracks and choose colours

1. Open **Automation → Edit layout → Train visualizer**.
2. Click a rail section, choose its **Track block**, and click **Assign block**.
3. Assign other sections to the same block to group them together.
4. Select a block in the colour key below the canvas and click **Edit block** to
   change its **Track colour**.
5. Click **Save layout** to preserve assignments, colours and geometry.

The colour key lists every block and the number of sections assigned to it.
Clicking a block highlights all its rails. Blocks without assigned tracks are
labelled **No tracks**. Geometry nodes and spline points are visible while editing;
the normal view shows rails, block boundaries, switches and trains.

## Put a boundary inside a track

Select a section, enter **Split at %**, and click **+ Block boundary**. The split
position runs from the first named anchor to the second along the cubic curve.
The curve is subdivided exactly: splitting does not change its shape, block
assignment or speed limit. Assign a different block to one of the resulting
sections. A boundary bar appears where the owners change. Adjacent sections with
the same owner have no boundary, even if there is a spline point between them.

Adding a regular spline point also inherits its section's assignment. Removing a
point between different blocks is rejected. Assign both sides to the same block
before removing that boundary. Joining sections retains their shared owner and
the lowest speed limit.

## Dragging trains and rolling stock

Drag standalone wagons to reposition them immediately. For a locomotive or a
train with a locomotive, hold **Shift** while dragging to choose the same direct
placement. The preview reads **PLACE**. Releasing Shift during that drag keeps
placement selected, so it cannot turn into a drive command at release.

Ordinary locomotive dragging keeps the **DEST** preview and calibrated movement
workflow, including confirmation on physical hardware. Direct placement needs
no calibration, works with track power off, and requires the selected train and
its routines to be stopped. Drop on a configured rail; dropping elsewhere or
cancelling a drag leaves its position unchanged.

In simulation, placement updates the simulator location at zero speed. On
physical hardware it changes the marker only; identified train locations and
detector occupancy remain authoritative. The manual marker lasts for the current
controller session and survives browser refreshes. Driving or a new identified
location supersedes it.

## Existing layouts and routing

Older layouts open without conversion. Sections without an explicit assignment
use the second block in alphabetical connection order, consistently in both
directions. Review these defaults in the visualizer and assign sections to match
your physical layout. New assignments are stored as `TrackSection.block_id`;
custom colours are stored as `Block.color`.

Assignments describe track coverage in the visualizer. They do not merge routing
nodes, change train routes, or remap hardware detectors. Routes continue to use
the existing connections, and detector mappings still target the same logical
block IDs. A block rename updates section references; a block that owns track
sections cannot be deleted until those sections are reassigned.
