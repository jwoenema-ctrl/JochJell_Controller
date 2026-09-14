"""Windows-only, packet-free preflight for the Roco 10814 WLAN profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
from ctypes import wintypes
import socket
import struct
import sys
from typing import Protocol


IF_TYPE_IEEE80211 = 71
_ACTIVE_LEGACY_OPER_STATES = {4, 5}  # connected, operational
_NO_ERROR = 0


class WlanPreflightError(RuntimeError):
    """Raised before Z21 transport creation when WLAN routing is unsafe."""


@dataclass(frozen=True)
class WlanAdapter:
    interface_index: int
    interface_type: int
    operational_status: int
    name: str = ""

    @property
    def is_wlan(self) -> bool:
        return self.interface_type == IF_TYPE_IEEE80211

    @property
    def is_active(self) -> bool:
        return self.operational_status in _ACTIVE_LEGACY_OPER_STATES


@dataclass(frozen=True)
class WlanPreflightStatus:
    profile: str
    state: str
    ready: bool
    host: str
    interface_index: int
    interface_name: str
    detail: str

    def as_dict(self) -> dict[str, str | int | bool]:
        return asdict(self)


class WindowsRouteAPI(Protocol):
    """Injectable view of the Windows routing and interface tables."""

    def best_interface(self, host: str) -> int: ...

    def interface(self, interface_index: int) -> WlanAdapter: ...


class _MibIfRow(ctypes.Structure):
    _fields_ = [
        ("wszName", ctypes.c_wchar * 256),
        ("dwIndex", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwMtu", wintypes.DWORD),
        ("dwSpeed", wintypes.DWORD),
        ("dwPhysAddrLen", wintypes.DWORD),
        ("bPhysAddr", ctypes.c_ubyte * 8),
        ("dwAdminStatus", wintypes.DWORD),
        ("dwOperStatus", wintypes.DWORD),
        ("dwLastChange", wintypes.DWORD),
        ("dwInOctets", wintypes.DWORD),
        ("dwInUcastPkts", wintypes.DWORD),
        ("dwInNUcastPkts", wintypes.DWORD),
        ("dwInDiscards", wintypes.DWORD),
        ("dwInErrors", wintypes.DWORD),
        ("dwInUnknownProtos", wintypes.DWORD),
        ("dwOutOctets", wintypes.DWORD),
        ("dwOutUcastPkts", wintypes.DWORD),
        ("dwOutNUcastPkts", wintypes.DWORD),
        ("dwOutDiscards", wintypes.DWORD),
        ("dwOutErrors", wintypes.DWORD),
        ("dwOutQLen", wintypes.DWORD),
        ("dwDescrLen", wintypes.DWORD),
        ("bDescr", ctypes.c_ubyte * 256),
    ]


class CtypesWindowsRouteAPI:
    """Read Windows route/interface tables through IP Helper API calls."""

    def __init__(self, library=None) -> None:
        if sys.platform != "win32" and library is None:
            raise WlanPreflightError("Windows route inspection is unavailable on this operating system.")
        self._library = library if library is not None else ctypes.WinDLL("iphlpapi")
        self._library.GetBestInterfaceEx.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
        self._library.GetBestInterfaceEx.restype = wintypes.DWORD
        self._library.GetIfEntry.argtypes = (ctypes.POINTER(_MibIfRow),)
        self._library.GetIfEntry.restype = wintypes.DWORD

    def best_interface(self, host: str) -> int:
        # sockaddr_in: native-endian address family, network-order port/address.
        address = struct.pack("=H", socket.AF_INET) + b"\0\0" + socket.inet_aton(host) + (b"\0" * 8)
        sockaddr = ctypes.create_string_buffer(address)
        interface_index = wintypes.DWORD()
        result = int(self._library.GetBestInterfaceEx(ctypes.byref(sockaddr), ctypes.byref(interface_index)))
        if result != _NO_ERROR:
            raise WlanPreflightError(
                f"Windows has no usable route to Z21 at {host} (IP Helper error {result}). "
                "Join the Roco/Z21 Wi-Fi network, then try again."
            )
        return int(interface_index.value)

    def interface(self, interface_index: int) -> WlanAdapter:
        row = _MibIfRow()
        row.dwIndex = interface_index
        result = int(self._library.GetIfEntry(ctypes.byref(row)))
        if result != _NO_ERROR:
            raise WlanPreflightError(
                f"Windows could not inspect network interface {interface_index} (IP Helper error {result}). "
                "Reconnect to the Roco/Z21 Wi-Fi network, then try again."
            )
        length = min(int(row.dwDescrLen), len(row.bDescr))
        description = bytes(row.bDescr[:length]).rstrip(b"\0").decode("utf-8", errors="replace")
        return WlanAdapter(interface_index, int(row.dwType), int(row.dwOperStatus), description or row.wszName.rstrip("\0"))


def preflight_z21_wlan(
    host: str,
    *,
    route_api: WindowsRouteAPI | None = None,
    platform_name: str | None = None,
) -> dict[str, str | int | bool]:
    """Confirm that Windows would route the Z21 host over active Wi-Fi.

    This reads local routing/interface tables only. It deliberately performs no
    ping, socket creation, DNS lookup, or Z21 protocol exchange.
    """

    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name != "win32":
        raise WlanPreflightError(
            "Roco 10814 WLAN preflight is supported only on Windows. "
            "Start in simulation, or disable the WLAN profile and use a verified wired Z21 connection."
        )
    api = route_api if route_api is not None else CtypesWindowsRouteAPI()
    try:
        interface_index = api.best_interface(host)
        adapter = api.interface(interface_index)
    except WlanPreflightError:
        raise
    except Exception as error:
        raise WlanPreflightError(
            f"Windows network-route inspection failed for Z21 at {host}: {error}. "
            "Join the Roco/Z21 Wi-Fi network, then try again."
        ) from error
    if not adapter.is_wlan:
        raise WlanPreflightError(
            f"Windows routes Z21 at {host} through a non-WLAN adapter. "
            "Join the Roco/Z21 Wi-Fi network in Windows, then try again."
        )
    if not adapter.is_active:
        raise WlanPreflightError(
            f"The WLAN adapter selected for Z21 at {host} is not connected. "
            "Join the Roco/Z21 Wi-Fi network in Windows, then try again."
        )
    name = adapter.name or f"Wi-Fi interface {interface_index}"
    return WlanPreflightStatus(
        profile="wlan",
        state="ready",
        ready=True,
        host=host,
        interface_index=interface_index,
        interface_name=name,
        detail=f"Windows routes the Z21 address through active WLAN interface {name}.",
    ).as_dict()
