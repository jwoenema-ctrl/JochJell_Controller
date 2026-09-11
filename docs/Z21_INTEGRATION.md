# Z21 integration boundary

The first milestone defaults to `SimulatedTrackSystem`. The real adapter is opt-in:
`Z21LanTransport` opens a UDP socket only when asked, checks the connection before sending,
and refuses command packets while disconnected.

The adapter follows the Z21 LAN framing used by the command station:

- UDP port `21105` is the normal control port; `21106` is the alternate port.
- Packets are little-endian records with a two-byte total length, two-byte header, and data.
- X-BUS command builders are included for version checks, locomotive drive commands, turnout
commands, and clean logoff.

The adapter also exposes the documented LAN X-BUS track-power on/off command, so the dashboard's
track-power control has the same command boundary as locomotive and turnout control.

R-BUS feedback polling is available through `Z21TrackSystem.bind_feedback()` and
`poll_feedback()`. Each mapped contact becomes protected physical occupancy in the dispatcher;
the current adapter deliberately labels it as a sensor until RailCom or a separate train-ID
service can associate the contact with a specific train.

`Z21TrackSystem` translates normalized application commands into those packets. It intentionally
requires a DCC address for real train control; the train database owns that mapping so UI IDs and
hardware addresses do not get mixed. `ControllerRuntime.create_z21(host, port=21105)` composes
the real adapter with the same dispatcher, scheduler, route updater and safety services used by
simulation. Call the connection checker before registering or driving trains.

Before enabling real operation, validate the Z21 IP address, track power, decoder addresses,
feedback hardware, and emergency-stop behavior on an isolated test layout.

The dashboard treats track-power off as a stop boundary: it stops all registered trains before
requesting the Z21 power change, marks their control mode as stopped, and only commits the UI
state after the adapter accepts the command. A rejected hardware command leaves the previous
power state visible so an operator can retry safely.

## Run the dashboard against a Z21

The dashboard remains simulation-first. To opt into the physical adapter, configure the Z21
address before starting the Visual Studio entry point:

```powershell
$env:H0_Z21_HOST = "192.168.0.111"
$env:H0_Z21_PORT = "21105"
$env:H0_Z21_FEEDBACK_MAP = "1:1=B01,1:2=B02"
python "Train Controller/Train_Controller.py"
```

Startup performs the bounded version check and registers the train addresses from the sample
profiles. It does not issue movement commands during startup. Speed and turnout commands are sent
only after the connection check has succeeded. Remove `H0_Z21_HOST` to return to simulation mode.
`H0_Z21_FEEDBACK_MAP` uses `module:input=block` entries separated by commas; omit it when no
R-BUS occupancy modules are installed.

Reference: [Z21 LAN Protocol Specification](https://www.z21.eu/media/Kwc_Basic_DownloadTag_Component/root-en-main_47-1652-959-downloadTag-download/default/d559b9cf/1628743384/z21-lan-protokoll-en.pdf).
