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
    "dispatch": ["layout-info", "node-graph", "systematic", "trains", "timetable"],
    "layout": ["layout-info", "node-graph", "automation", "systematic", "routes", "scans", "timetable"],
    "trains": ["trains", "train-profile", "rolling-stock", "programming", "calibration", "assembler"],
    "timetable": ["timetable"],
    "scans": ["scans"],
}
CONTROL_PANELS = ["control-center", "selected-train", "train-functions", "simulation", "connection-health"]
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
    def migrate_legacy_order(page: str, key: str, order: Any) -> Any:
        if page == "layout" and key == "order" and isinstance(order, list):
            legacy = ["layout-info", "node-graph", "systematic"]
            if len(order) == len(legacy) and all(isinstance(item, str) for item in order) and set(order) == set(legacy):
                return list(order) + ["automation", "routes", "scans", "timetable"]
            legacy = ["layout-info", "node-graph", "systematic", "routes", "scans"]
            if len(order) == len(legacy) and all(isinstance(item, str) for item in order) and set(order) == set(legacy):
                return list(order) + ["automation", "timetable"]
        if page == "dispatch" and key == "order" and isinstance(order, list):
            legacy = ["layout-info", "node-graph", "systematic", "trains"]
            if len(order) == len(legacy) and all(isinstance(item, str) for item in order) and set(order) == set(legacy):
                return list(order) + ["timetable"]
        if page == "trains" and key == "order" and isinstance(order, list):
            legacy = ["trains", "train-profile", "assembler"]
            if len(order) == len(legacy) and all(isinstance(item, str) for item in order) and set(order) == set(legacy):
                return ["trains", "train-profile", "rolling-stock", "programming", "calibration", "assembler"]
        if page in ("dispatch", "trains") and key == "sidebar_order" and isinstance(order, list):
            legacy = ["control-center", "selected-train", "simulation", "connection-health"]
            if len(order) == len(legacy) and all(isinstance(item, str) for item in order) and set(order) == set(legacy):
                return ["control-center", "selected-train", "train-functions", "simulation", "connection-health"]
        return order

    if current:
        for page, preferences in current.get("pages", {}).items():
            if page in result["pages"]:
                migrated = deepcopy(preferences)
                for key in ("order", "sidebar_order"):
                    if key in migrated:
                        migrated[key] = migrate_legacy_order(page, key, migrated[key])
                result["pages"][page].update(migrated)
    for page, patch in pages.items():
        if not isinstance(patch, dict) or set(patch) - {"order", "sidebar_order", "sidebar_side"}:
            raise ValueError(f"invalid workspace preferences for {page}")
        migrated = deepcopy(patch)
        for key in ("order", "sidebar_order"):
            if key in migrated:
                migrated[key] = migrate_legacy_order(page, key, migrated[key])
        result["pages"][page].update(migrated)
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
    "interface": {
        "density": "comfortable",
        "show_connection_detail": True,
        "reduce_motion": False,
    },
    "operations": {
        "confirm_power_actions": False,
        "default_simulation_rate": 1,
        "connected_blocks": True,
    },
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
    result.update({key: item for key, item in value.items() if key not in ("routing", "workspace_layout", "interface", "operations")})
    result["routing"].update(routing)
    interface = value.get("interface", {})
    if not isinstance(interface, dict) or set(interface) - set(DEFAULT_SETTINGS["interface"]):
        raise ValueError("interface must contain only known settings")
    result["interface"].update(interface)
    operations = value.get("operations", {})
    if not isinstance(operations, dict) or set(operations) - set(DEFAULT_SETTINGS["operations"]):
        raise ValueError("operations must contain only known settings")
    result["operations"].update(operations)
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
    if result["interface"]["density"] not in ("comfortable", "compact"):
        raise ValueError("interface.density must be comfortable or compact")
    for key in ("show_connection_detail", "reduce_motion"):
        if type(result["interface"][key]) is not bool:
            raise ValueError(f"interface.{key} must be a boolean")
    if type(result["operations"]["confirm_power_actions"]) is not bool:
        raise ValueError("operations.confirm_power_actions must be a boolean")
    if type(result["operations"]["connected_blocks"]) is not bool:
        raise ValueError("operations.connected_blocks must be a boolean")
    if type(result["operations"]["default_simulation_rate"]) is not int or result["operations"]["default_simulation_rate"] not in (1, 5, 15, 60):
        raise ValueError("operations.default_simulation_rate must be one of 1, 5, 15, or 60")
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
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS automation_programs ("
                "id TEXT PRIMARY KEY, position INTEGER NOT NULL, data_json TEXT NOT NULL)"
            )

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

    def load_automation_programs(self) -> list[dict[str, Any]]:
        """Load authored automation routines stored beside application settings."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT data_json FROM automation_programs ORDER BY position, id"
            ).fetchall()
        programs: list[dict[str, Any]] = []
        for (raw,) in rows:
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict) and str(value.get("id", "")).strip():
                programs.append(value)
        return programs

    def replace_automation_programs(self, programs: list[Mapping[str, Any]]) -> None:
        """Atomically replace the authored automation routine catalogue."""

        with self._lock, self._connection:
            self._connection.execute("DELETE FROM automation_programs")
            self._connection.executemany(
                "INSERT INTO automation_programs (id, position, data_json) VALUES (?, ?, ?)",
                [
                    (
                        str(program.get("id", "")),
                        index,
                        json.dumps(dict(program), separators=(",", ":")),
                    )
                    for index, program in enumerate(programs)
                ],
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
