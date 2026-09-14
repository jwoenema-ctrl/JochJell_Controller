"""Validated, durable application preferences; never a hardware activation switch."""

from __future__ import annotations

from copy import deepcopy
import ipaddress
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping


WORKSPACE_PANELS = {
    "dispatch": ["layout-info", "node-graph", "systematic", "trains"],
    "layout": ["layout-info", "node-graph", "systematic"],
    "trains": ["trains", "train-profile", "assembler"],
    "timetable": ["timetable"],
    "scans": ["scans"],
}
CONTROL_PANELS = ["control-center", "selected-train", "simulation", "connection-health"]
DEFAULT_WORKSPACE_LAYOUT = {
    "pages": {
        page: {
            "order": panels.copy(),
            "sidebar_order": CONTROL_PANELS.copy() if page in ("dispatch", "trains") else [],
            "sidebar_side": "left",
        }
        for page, panels in WORKSPACE_PANELS.items()
    }
}


def validate_workspace_layout(value: Any, current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge per-page patches without accepting arbitrary DOM selectors or CSS."""
    if not isinstance(value, dict) or set(value) - {"pages"}:
        raise ValueError("workspace_layout must be an object containing pages")
    pages = value.get("pages", {})
    if not isinstance(pages, dict) or set(pages) - set(WORKSPACE_PANELS):
        raise ValueError("unknown workspace page")
    result = deepcopy(DEFAULT_WORKSPACE_LAYOUT)
    if current:
        for page, preferences in current.get("pages", {}).items():
            if page in result["pages"]:
                result["pages"][page].update(deepcopy(preferences))
    for page, patch in pages.items():
        if not isinstance(patch, dict) or set(patch) - {"order", "sidebar_order", "sidebar_side"}:
            raise ValueError(f"invalid workspace preferences for {page}")
        result["pages"][page].update(deepcopy(patch))
    for page, preferences in result["pages"].items():
        if preferences["sidebar_side"] not in ("left", "right"):
            raise ValueError("sidebar_side must be left or right")
        for key in ("order", "sidebar_order"):
            order = preferences[key]
            expected = DEFAULT_WORKSPACE_LAYOUT["pages"][page][key]
            if (not isinstance(order, list) or any(not isinstance(item, str) for item in order)
                    or len(order) != len(expected) or set(order) != set(expected)):
                raise ValueError(f"{page}.{key} must contain each available panel exactly once")
    return result


DEFAULT_SETTINGS = {
    "theme": "system",
    "z21_host": "192.168.0.111",
    "z21_port": 21105,
    "z21_wlan_enabled": False,
    "ui_refresh_ms": 5000,
    "routing": {"adaptive": True, "busy_interval_ms": 1000, "idle_interval_ms": 5000},
    "workspace_layout": DEFAULT_WORKSPACE_LAYOUT,
}


def validate_settings(value: Mapping[str, Any], current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate an entire patch before applying it; accept partial nested updates."""

    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    unknown = set(value) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    result = deepcopy(DEFAULT_SETTINGS)
    if current:
        result.update(deepcopy(dict(current)))
    routing = value.get("routing", {})
    if not isinstance(routing, dict):
        raise ValueError("routing must be an object")
    if set(routing) - set(DEFAULT_SETTINGS["routing"]):
        raise ValueError("unknown routing setting")
    result["workspace_layout"] = validate_workspace_layout(value.get("workspace_layout", {}), result["workspace_layout"])
    result.update({key: item for key, item in value.items() if key not in ("routing", "workspace_layout")})
    result["routing"].update(routing)
    if result["theme"] not in ("system", "light", "dark"):
        raise ValueError("theme must be system, light, or dark")
    try:
        host = result["z21_host"]
        if not isinstance(host, str):
            raise ValueError()
        # The Z21 LAN transport uses IPv4 UDP. DNS names and URLs are not accepted.
        result["z21_host"] = str(ipaddress.IPv4Address(host.strip()))
    except (ValueError, ipaddress.AddressValueError):
        raise ValueError("z21_host must be a valid IPv4 address") from None
    for key, low, high in (("z21_port", 1, 65535), ("ui_refresh_ms", 1000, 60000)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"{key} must be an integer between {low} and {high}")
    if type(result["z21_wlan_enabled"]) is not bool:
        raise ValueError("z21_wlan_enabled must be a boolean")
    if type(result["routing"]["adaptive"]) is not bool:
        raise ValueError("routing.adaptive must be a boolean")
    for key in ("busy_interval_ms", "idle_interval_ms"):
        item = result["routing"][key]
        if type(item) is not int or not 250 <= item <= 60000:
            raise ValueError(f"routing.{key} must be an integer between 250 and 60000")
    return result


class SQLiteSettingsRepository:
    """Keep settings alongside the train database, isolated from layout saves."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        with self._connection:
            self._connection.execute("CREATE TABLE IF NOT EXISTS app_settings (id INTEGER PRIMARY KEY CHECK (id = 1), data_json TEXT NOT NULL)")

    def load(self) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT data_json FROM app_settings WHERE id = 1").fetchone()
        return validate_settings(json.loads(row[0])) if row else deepcopy(DEFAULT_SETTINGS)

    def save(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_settings(dict(settings))
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO app_settings (id, data_json) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json",
                (json.dumps(validated, separators=(",", ":")),),
            )
        return validated

    def close(self) -> None:
        with self._lock:
            self._connection.close()
