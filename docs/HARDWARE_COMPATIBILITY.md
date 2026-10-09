# Digital system connections

Choose a digital system in **Settings → Hardware connection**, enter its network
or serial connection, and save. **Connect** explicitly activates the saved
connection with track power off. **Disconnect / use simulation** stops the
hardware connection and returns to simulation. Saving preferences alone does not
open a connection or enable track power. These controls work in the browser and
the desktop application.

Python process startup defaults to simulation, even when a physical profile is
saved. Set `H0_TRACK_SYSTEM=hardware` to activate the saved selection, or use a
profile ID such as `ecos`, `marklin_cs3`, or `xpressnet`. The desktop launcher's
**Hardware · saved digital system** option uses the same saved selection.
`H0_HARDWARE_HOST`, `H0_HARDWARE_PORT`, `H0_HARDWARE_SERIAL_PORT`,
`H0_HARDWARE_BAUDRATE`, `H0_HARDWARE_DECODER_PROTOCOL`, and
`H0_HARDWARE_TRANSPORT` provide explicit process overrides. The transport override
is `lan`, `wlan`, `serial`, or `simulation` as applicable to the profile. Existing
`H0_Z21_HOST`, `H0_Z21_PORT`, and `H0_Z21_FEEDBACK_MAP` remain available for Z21
installations; `H0_HARDWARE_FEEDBACK_MAP` is the generic detector mapping override.

The layout, train catalogue, consists, routines, timetable, world clock, and
visualizer use the same controller regardless of the station. Available hardware
operations depend on the selected adapter. The interface shows the selected
profile's capabilities and disables unsupported programming or scanning controls.

## Profiles and connection requirements

| Settings option | Computer connection | Required station configuration |
| --- | --- | --- |
| Simulation | Local | No command station required. |
| Roco Z21 | UDP, default port 21105 | Station and controller computer must reach each other. |
| Roco z21 (white) | UDP, default port 21105 | LAN control enabled; installed feedback hardware determines available feedback. |
| Roco z21start | UDP, default port 21105 | Unlock LAN control before connecting. The WLAN package is one way to provide the unlock and router. |
| Digikeijs DR5000 (Z21 mode) | UDP, default port 21105 | Select Z21 as the station's LAN protocol. Use the actual station IP address. |
| Märklin Central Station 2 | CAN over UDP, commands to 15731 | Enable the CAN gateway and set its broadcast destination to the controller computer. Responses arrive on UDP 15730. |
| Märklin Central Station 3 | CAN over UDP, commands to 15731 | Enable the CAN gateway and set its broadcast destination to the controller computer. Responses arrive on UDP 15730. |
| ESU ECoS | TCP, default port 15471 | Enable PC control. Locomotives use station objects. Create turnout objects with PULSE mode and a configured duration of 250–2500 ms; the adapter checks this before switching a coil. |
| Roco/Lenz XpressNet (LI-USB interface) | Serial, default 57600 baud | Use an LI-USB compatible PC interface and the correct operating-system serial port. A multiMAUS with a 10764 amplifier alone does not provide a PC interface. |

Network defaults are starting values. Set the IP address assigned on your own
network; an address copied from another station is not discovery. For serial
interfaces, use a port on the computer running the Python controller, such as
`COM3` on Windows or `/dev/ttyUSB0` on Linux. Install the interface's serial driver
and the optional Python serial dependency when required:

```console
python -m pip install -r requirements-hardware.txt
```

## Wi-Fi

All network profiles can use **Connect over Wi-Fi**. LAN and Wi-Fi send the same
station protocol to the configured IP and port. Wi-Fi is a network connection
choice, not a different decoder protocol.

Join a network that reaches the station on the computer running the controller
before pressing Connect. The application does not join Wi-Fi, store its password,
or configure a router. The Roco WLAN package and the DR5000's configured wireless
network can provide that connection. For a station connected by Ethernet, a
wireless router or bridge can provide access; this does not imply that the station
contains a Wi-Fi radio. Guest-network isolation and firewall rules can prevent
the required traffic, including station feedback.

## Decoder identities and mixed consists

Train profiles retain their decoder protocol. The connection's default protocol
is used when a train does not specify one. Z21-compatible and XpressNet adapters
in this controller use DCC. Märklin and ECoS profiles offer DCC, Motorola, and mfx.
Unsupported saved protocols remain visible in the catalogue, but must be corrected
or used with a compatible station before movement can be sent.

For Märklin mfx, the train's address field is the **station-assigned SID**, not the
decoder's raw UID. For ECoS mfx, enter the station's locomotive object ID. DCC and
Motorola entries use their configured decoder addresses. A protocol selection does
not convert or reprogram a decoder.

Rolling stock function entries remain explicitly DCC. Their function commands
target the car's saved DCC address, even when the locomotive uses another protocol.
Cars sharing a DCC address respond together and their controls share function
state. To control otherwise identical cars separately, create catalogue entries
with distinct decoder addresses.

## Adapter capabilities

| Adapter family | Train/function/turnout/power control | Feedback | Decoder programming | Additional operations |
| --- | --- | --- | --- | --- |
| Simulation | Simulated | Simulated | Validation/simulation | Address scan simulation |
| Roco Z21 / z21 / z21start | Yes | R-Bus and available station feedback | DCC programming track and main-track operations | Station electrical readings, RailCom, address scan where supported by hardware |
| DR5000 in Z21 mode | Yes | Mapped Z21 feedback | DCC programming track and main-track operations | Electrical telemetry, RailCom and address scans are not advertised by this profile |
| Märklin CS2 / CS3 | Yes | Mapped CAN feedback | Not implemented through this adapter | No electrical telemetry or address scan advertised |
| ESU ECoS | Yes | Mapped station feedback | Not implemented through this adapter | No electrical telemetry or address scan advertised |
| XpressNet LI-USB | Yes | Mapped XpressNet feedback | Not implemented through this adapter | F0–F28; no electrical telemetry or address scan advertised |

These are adapter capabilities, not a complete specification of each station.
Connected detectors, decoder support, station settings and firmware still determine
which feedback or programming operations can succeed. Configure detector-to-block
mappings appropriate to the selected system. An interface without occupancy
feedback cannot independently confirm that a physical block is clear.

The decoder programming panel handles DCC. Motorola and mfx decoder configuration
must be performed using the station's own programming interface.

## Verification status

The existing Z21 implementation remains the compatibility baseline. The other
adapters are implemented against their documented protocols and can be checked
with simulated protocol peers. Physical verification of the new station families
is pending; the development setup currently has a Z21 available. Protocol checks
do not prove operation with every firmware version, decoder, feedback module or
computer interface. No live train or track-power commands are needed to verify
the Settings interface.

Protocol references used by the adapters:

- [Roco Z21 LAN protocol](https://www.z21.eu/en/downloads/manuals)
- [Digikeijs DR5000 manufacturer manual archive](https://archive.traintastic.org/digikeijs/DR5000-Manual.pdf)
- [Märklin CAN protocol 2.0](https://streaming.maerklin.de/public-media/cs2/cs2CAN-Protokoll-2_0.pdf)
- [ESU ECoS PC interface specification](https://www.esu.eu/uploads/tx_esudownloads/ECoS_PC-Schnittstellenbeschreibung_ESUKG_DE_Auflage_I.pdf)
- [Lenz XpressNet documentation](https://www.lenz-elektronik.de/digital-plus/xpressnet.php)
