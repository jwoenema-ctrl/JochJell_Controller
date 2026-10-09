"""Command-station profiles and validated connection preferences.

Profiles describe implemented adapter capabilities, not every feature a station
may offer. Selecting or saving a profile never opens a transport.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import ipaddress
from typing import Any, Mapping


_BASE_CAPABILITIES = dict(speed=True, direction=True, functions=True, turnouts=True,
                          feedback=True, power=True, telemetry=False, programming=False,
                          pom=False, railcom=False, address_scan=False)


@dataclass(frozen=True)
class HardwareProfile:
    id: str
    label: str
    transport: str
    default_port: int
    detail: str
    decoder_protocols: tuple[str, ...] = ("dcc",)
    default_host: str = "192.168.0.111"
    default_baudrate: int = 115200
    max_functions: int = 32
    extra_capabilities: tuple[str, ...] = ()
    disabled_capabilities: tuple[str, ...] = ()

    @property
    def capabilities(self) -> dict[str, bool]:
        result = dict(_BASE_CAPABILITIES)
        result.update({name: True for name in self.extra_capabilities})
        result.update({name: False for name in self.disabled_capabilities})
        return result

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "transport": self.transport,
                "default_host": self.default_host, "default_port": self.default_port,
                "default_baudrate": self.default_baudrate, "max_functions": self.max_functions,
                "detail": self.detail, "decoder_protocols": list(self.decoder_protocols),
                "supports_wlan": self.transport in ("udp", "tcp"),
                "connection_help": ("WLAN connects through your router or wireless bridge using the station IP; it does not require built-in station Wi-Fi."
                                    if self.transport in ("udp", "tcp") else self.detail),
                "capabilities": self.capabilities}


HARDWARE_PROFILES = {
    profile.id: profile for profile in (
        HardwareProfile("simulation", "Simulation", "simulation", 21105,
                        "Use the built-in simulator without connecting to hardware.",
                        extra_capabilities=("programming", "pom", "address_scan")),
        HardwareProfile("z21", "Roco Z21", "udp", 21105,
                        "Z21 LAN protocol with R-Bus feedback.",
                        extra_capabilities=("telemetry", "programming", "pom", "railcom", "address_scan")),
        HardwareProfile("z21_white", "Roco z21 (white)", "udp", 21105,
                        "Uses the Z21 LAN interface; feedback availability depends on the station.",
                        extra_capabilities=("telemetry", "programming", "pom", "railcom", "address_scan")),
        HardwareProfile("z21_start", "Roco z21start", "udp", 21105,
                        "LAN control must be unlocked on the station before connecting.",
                        extra_capabilities=("telemetry", "programming", "pom", "railcom", "address_scan")),
        HardwareProfile("dr5000", "Digikeijs DR5000 (Z21 mode)", "udp", 21105,
                        "Configure the station LAN protocol as Z21 before connecting.",
                        extra_capabilities=("programming", "pom")),
        HardwareProfile("marklin_cs2", "Märklin Central Station 2", "udp", 15731,
                        "Enable the station CAN gateway and configure its broadcast destination.",
                        decoder_protocols=("dcc", "mm", "mfx")),
        HardwareProfile("marklin_cs3", "Märklin Central Station 3", "udp", 15731,
                        "Enable the station CAN gateway and configure its broadcast destination.",
                        decoder_protocols=("dcc", "mm", "mfx")),
        HardwareProfile("ecos", "ESU ECoS", "tcp", 15471,
                        "Enable PC control. Locomotives use station objects; configure turnout objects in PULSE mode with a bounded duration.",
                        decoder_protocols=("dcc", "mm", "mfx")),
        HardwareProfile("xpressnet", "Roco/Lenz XpressNet (LI-USB interface)", "serial", 21105,
                        "Requires an LI-USB compatible PC interface; a multiMAUS and 10764 amplifier alone have no PC connection.",
                        default_baudrate=57600, max_functions=29),
    )
}

Z21_COMPATIBLE_SYSTEMS = frozenset(("z21", "z21_white", "z21_start", "dr5000"))
DEFAULT_HARDWARE = dict(system="z21", host="192.168.0.111", port=21105,
                        serial_port="", baudrate=115200, decoder_protocol="dcc", transport="lan")


def hardware_profile(system: str) -> HardwareProfile:
    try:
        return HARDWARE_PROFILES[system]
    except (KeyError, TypeError):
        raise ValueError("unknown hardware system") from None


def hardware_profiles() -> list[dict[str, Any]]:
    return [profile.payload() for profile in HARDWARE_PROFILES.values()]


get_profile = hardware_profile


def create_track_system(system: str, *, host: str = "192.168.0.111", port: int | None = None,
                        serial_port: str = "", baudrate: int | None = None, decoder_protocol: str = "dcc",
                        transport: str | None = None,
                        feedback_map: Mapping[tuple[int, int], str] | None = None):
    """Open a selected station adapter only after explicit activation."""
    profile = hardware_profile(system)
    requested = dict(system=system, host=host, port=port if port is not None else profile.default_port,
                     serial_port=serial_port, baudrate=baudrate if baudrate is not None else profile.default_baudrate,
                     decoder_protocol=decoder_protocol)
    if transport is not None:
        requested["transport"] = transport
    value = validate_hardware(requested)
    if system == "simulation":
        from .simulation import SimulatedTrackSystem
        return SimulatedTrackSystem()
    if system in Z21_COMPATIBLE_SYSTEMS:
        from .z21 import Z21LanTransport
        from .real_track import Z21TrackSystem
        transport = Z21LanTransport(value["host"], port=value["port"])
        try:
            transport.open()
            return Z21TrackSystem(transport, feedback_map=feedback_map)
        except BaseException:
            transport.close()
            raise
    if system in ("marklin_cs2", "marklin_cs3"):
        from .marklin import MarklinTrackSystem
        return MarklinTrackSystem(value["host"], port=value["port"], feedback_map=feedback_map,
                                  decoder_protocol=value["decoder_protocol"])
    if system == "ecos":
        from .ecos import ECoSTrackSystem
        return ECoSTrackSystem(value["host"], port=value["port"], feedback_map=feedback_map,
                              decoder_protocol=value["decoder_protocol"])
    if system == "xpressnet":
        from .xpressnet import XpressNetTrackSystem
        return XpressNetTrackSystem(serial_port=value["serial_port"], baudrate=value["baudrate"],
                                   feedback_map=feedback_map, decoder_protocol=value["decoder_protocol"])
    raise ValueError("unknown hardware system")


def validate_hardware(value: Any, current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(DEFAULT_HARDWARE):
        raise ValueError("hardware must contain only known connection settings")
    result = deepcopy(DEFAULT_HARDWARE)
    if current:
        result.update(dict(current))
    previous_system = result["system"]
    result.update(value)
    profile = hardware_profile(result["system"])
    if profile.id != previous_system:
        if "port" not in value:
            result["port"] = profile.default_port
        if "baudrate" not in value:
            result["baudrate"] = profile.default_baudrate
        if "decoder_protocol" not in value:
            result["decoder_protocol"] = profile.decoder_protocols[0]
        if "transport" not in value:
            result["transport"] = (profile.transport if profile.transport in ("serial", "simulation") else "lan")
    allowed_transport = ((profile.transport,) if profile.transport in ("serial", "simulation") else ("lan", "wlan"))
    if result["transport"] not in allowed_transport:
        raise ValueError("hardware.transport is not supported by this hardware profile")
    host = result["host"]
    try:
        if not isinstance(host, str):
            raise ValueError()
        result["host"] = str(ipaddress.IPv4Address(host.strip()))
    except ValueError:
        raise ValueError("hardware.host must be a valid IPv4 address") from None
    if type(result["port"]) is not int or not 1 <= result["port"] <= 65535:
        raise ValueError("hardware.port must be an integer between 1 and 65535")
    if type(result["baudrate"]) is not int or result["baudrate"] not in (9600, 19200, 38400, 57600, 115200):
        raise ValueError("hardware.baudrate must be a supported serial rate")
    if not isinstance(result["serial_port"], str) or len(result["serial_port"]) > 256:
        raise ValueError("hardware.serial_port must be a port name")
    result["serial_port"] = result["serial_port"].strip()
    if result["decoder_protocol"] not in profile.decoder_protocols:
        raise ValueError("decoder protocol is not supported by this hardware profile")
    return result
