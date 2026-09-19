"""SQLite persistence for H0 locomotive and rolling-stock model information."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import RLock
from typing import Any, Mapping


@dataclass(frozen=True)
class TrainModel:
    """A flexible train record with common model and decoder fields."""

    train_id: str
    name: str
    manufacturer: str = ""
    model: str = ""
    scale: str = "H0"
    decoder_address: int | None = None
    decoder_protocol: str = "DCC"
    era: str = ""
    length_mm: float | None = None
    mass_g: float | None = None
    max_speed_kmh: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecoderFunctionMapping:
    """A decoder function assignment for a train model."""

    train_id: str
    function_number: int
    name: str
    description: str = ""
    momentary: bool = False
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def function_name(self) -> str:
        return self.name


@dataclass(frozen=True)
class MaintenanceRecord:
    """A dated maintenance or service event for a train model."""

    train_id: str
    service_date: str
    service_type: str
    description: str = ""
    mileage_km: float | None = None
    cost: float | None = None
    performed_by: str = ""
    next_service_date: str | None = None
    record_id: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollingStockRecord:
    """One rolling-stock vehicle in a train's ordered consist."""

    train_id: str
    rolling_stock_id: str
    position: int = 0
    vehicle_type: str = "vehicle"
    name: str = ""
    manufacturer: str = ""
    model: str = ""
    length_mm: float | None = None
    mass_g: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def vehicle_id(self) -> str:
        return self.rolling_stock_id


@dataclass(frozen=True)
class RollingStockInventoryRecord:
    """One catalogued rolling-stock type with a changeable quantity."""

    item_id: str
    name: str
    vehicle_type: str = "vehicle"
    quantity: int = 0
    manufacturer: str = ""
    model: str = ""
    length_mm: float | None = None
    mass_g: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def rolling_stock_id(self) -> str:
        return self.item_id

    @property
    def inventory_id(self) -> str:
        return self.item_id

    @property
    def vehicle_id(self) -> str:
        return self.item_id


@dataclass(frozen=True)
class CalibrationRecord:
    """One measured short movement used to predict real train travel."""

    calibration_id: int | None
    train_id: str
    speed_kmh: float
    duration_ms: int
    measured_distance_mm: float
    created_at: str
    notes: str = ""


@dataclass(frozen=True)
class TrainDetails:
    """A train model together with its full persisted metadata."""

    train: TrainModel
    decoder_functions: tuple[DecoderFunctionMapping, ...] = ()
    maintenance_records: tuple[MaintenanceRecord, ...] = ()
    rolling_stock: tuple[RollingStockRecord, ...] = ()
    calibrations: tuple[CalibrationRecord, ...] = ()


DecoderFunction = DecoderFunctionMapping
ServiceRecord = MaintenanceRecord
ConsistRecord = RollingStockRecord
RollingStockInventory = RollingStockInventoryRecord
InventoryRecord = RollingStockInventoryRecord


class SQLiteTrainDatabase:
    """Thread-safe SQLite repository with no dependency beyond the stdlib."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = RLock()
        self._initialise()

    def _initialise(self) -> None:
        """Create the schema and add only missing columns to legacy databases."""

        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trains (
                    train_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    scale TEXT NOT NULL DEFAULT 'H0',
                    decoder_address INTEGER,
                    decoder_protocol TEXT NOT NULL DEFAULT 'DCC',
                    era TEXT NOT NULL DEFAULT '',
                    length_mm REAL,
                    mass_g REAL,
                    max_speed_kmh REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_columns(
                "trains",
                {
                    "manufacturer": "TEXT NOT NULL DEFAULT ''",
                    "model": "TEXT NOT NULL DEFAULT ''",
                    "scale": "TEXT NOT NULL DEFAULT 'H0'",
                    "decoder_address": "INTEGER",
                    "decoder_protocol": "TEXT NOT NULL DEFAULT 'DCC'",
                    "era": "TEXT NOT NULL DEFAULT ''",
                    "length_mm": "REAL",
                    "mass_g": "REAL",
                    "max_speed_kmh": "REAL",
                    "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                    # SQLite disallows CURRENT_TIMESTAMP in ALTER TABLE defaults.
                    "created_at": "TEXT",
                    "updated_at": "TEXT",
                },
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decoder_function_mappings (
                    train_id TEXT NOT NULL,
                    function_number INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    momentary INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (train_id, function_number),
                    FOREIGN KEY (train_id) REFERENCES trains(train_id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_columns(
                "decoder_function_mappings",
                {"description": "TEXT NOT NULL DEFAULT ''", "momentary": "INTEGER NOT NULL DEFAULT 0",
                 "enabled": "INTEGER NOT NULL DEFAULT 1", "metadata_json": "TEXT NOT NULL DEFAULT '{}'"},
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS maintenance_records (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    train_id TEXT NOT NULL,
                    service_date TEXT NOT NULL,
                    service_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    mileage_km REAL,
                    cost REAL,
                    performed_by TEXT NOT NULL DEFAULT '',
                    next_service_date TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (train_id) REFERENCES trains(train_id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_columns(
                "maintenance_records",
                {"description": "TEXT NOT NULL DEFAULT ''", "mileage_km": "REAL", "cost": "REAL",
                 "performed_by": "TEXT NOT NULL DEFAULT ''", "next_service_date": "TEXT",
                 "metadata_json": "TEXT NOT NULL DEFAULT '{}'"},
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rolling_stock_records (
                    train_id TEXT NOT NULL,
                    rolling_stock_id TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    vehicle_type TEXT NOT NULL DEFAULT 'vehicle',
                    name TEXT NOT NULL DEFAULT '',
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    length_mm REAL,
                    mass_g REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (train_id, rolling_stock_id),
                    FOREIGN KEY (train_id) REFERENCES trains(train_id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_columns(
                "rolling_stock_records",
                {"position": "INTEGER NOT NULL DEFAULT 0", "vehicle_type": "TEXT NOT NULL DEFAULT 'vehicle'",
                 "name": "TEXT NOT NULL DEFAULT ''", "manufacturer": "TEXT NOT NULL DEFAULT ''",
                 "model": "TEXT NOT NULL DEFAULT ''", "length_mm": "REAL", "mass_g": "REAL",
                 "metadata_json": "TEXT NOT NULL DEFAULT '{}'"},
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rolling_stock_inventory (
                    item_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    vehicle_type TEXT NOT NULL DEFAULT 'vehicle',
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    length_mm REAL,
                    mass_g REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_columns(
                "rolling_stock_inventory",
                {"vehicle_type": "TEXT NOT NULL DEFAULT 'vehicle'", "quantity": "INTEGER NOT NULL DEFAULT 0",
                 "manufacturer": "TEXT NOT NULL DEFAULT ''", "model": "TEXT NOT NULL DEFAULT ''",
                 "length_mm": "REAL", "mass_g": "REAL", "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                 "updated_at": "TEXT"},
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS train_calibrations (
                    calibration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    train_id TEXT NOT NULL,
                    speed_kmh REAL NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    measured_distance_mm REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (train_id) REFERENCES trains(train_id) ON DELETE CASCADE
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_maintenance_train_date "
                "ON maintenance_records(train_id, service_date DESC, record_id DESC)"
            )

    def _ensure_columns(self, table: str, columns: Mapping[str, str]) -> None:
        existing = {row[1] for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def upsert(self, train: TrainModel) -> TrainModel:
        """Insert or replace a model record and return it unchanged."""

        self._validate(train)
        values = (train.train_id, train.name, train.manufacturer, train.model, train.scale,
                  train.decoder_address, train.decoder_protocol, train.era, train.length_mm,
                  train.mass_g, train.max_speed_kmh, _dump_json(train.metadata))
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO trains (
                    train_id, name, manufacturer, model, scale, decoder_address,
                    decoder_protocol, era, length_mm, mass_g, max_speed_kmh, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(train_id) DO UPDATE SET
                    name = excluded.name, manufacturer = excluded.manufacturer,
                    model = excluded.model, scale = excluded.scale,
                    decoder_address = excluded.decoder_address,
                    decoder_protocol = excluded.decoder_protocol, era = excluded.era,
                    length_mm = excluded.length_mm, mass_g = excluded.mass_g,
                    max_speed_kmh = excluded.max_speed_kmh,
                    metadata_json = excluded.metadata_json, updated_at = CURRENT_TIMESTAMP
                """, values,
            )
        return train

    def get(self, train_id: str) -> TrainModel | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM trains WHERE train_id = ?", (train_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, scale: str | None = None) -> tuple[TrainModel, ...]:
        with self._lock:
            if scale is None:
                rows = self._connection.execute("SELECT * FROM trains ORDER BY name COLLATE NOCASE, train_id").fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM trains WHERE scale = ? ORDER BY name COLLATE NOCASE, train_id", (scale,)
                ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def delete(self, train_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM trains WHERE train_id = ?", (train_id,))
        return cursor.rowcount > 0

    def count(self) -> int:
        with self._lock:
            return int(self._connection.execute("SELECT COUNT(*) FROM trains").fetchone()[0])

    def upsert_decoder_function(self, mapping: DecoderFunctionMapping) -> DecoderFunctionMapping:
        self._validate_decoder_function(mapping)
        with self._lock, self._connection:
            self._require_train(mapping.train_id)
            self._connection.execute(
                """
                INSERT INTO decoder_function_mappings
                    (train_id, function_number, name, description, momentary, enabled, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(train_id, function_number) DO UPDATE SET
                    name = excluded.name, description = excluded.description,
                    momentary = excluded.momentary, enabled = excluded.enabled,
                    metadata_json = excluded.metadata_json
                """,
                (mapping.train_id, mapping.function_number, mapping.name, mapping.description,
                 int(mapping.momentary), int(mapping.enabled), _dump_json(mapping.metadata)),
            )
        return mapping

    upsert_decoder_function_mapping = upsert_decoder_function
    set_decoder_function = upsert_decoder_function

    def get_decoder_function(self, train_id: str, function_number: int) -> DecoderFunctionMapping | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM decoder_function_mappings WHERE train_id = ? AND function_number = ?",
                (train_id, function_number),
            ).fetchone()
        return self._decoder_function_from_row(row) if row else None

    def list_decoder_functions(self, train_id: str) -> tuple[DecoderFunctionMapping, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM decoder_function_mappings WHERE train_id = ? ORDER BY function_number", (train_id,)
            ).fetchall()
        return tuple(self._decoder_function_from_row(row) for row in rows)

    get_decoder_functions = list_decoder_functions

    def delete_decoder_function(self, train_id: str, function_number: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM decoder_function_mappings WHERE train_id = ? AND function_number = ?",
                (train_id, function_number),
            )
        return cursor.rowcount > 0

    remove_decoder_function = delete_decoder_function

    def upsert_maintenance_record(self, record: MaintenanceRecord) -> MaintenanceRecord:
        self._validate_maintenance_record(record)
        with self._lock, self._connection:
            self._require_train(record.train_id)
            values = (record.train_id, record.service_date, record.service_type, record.description,
                      record.mileage_km, record.cost, record.performed_by, record.next_service_date,
                      _dump_json(record.metadata))
            if record.record_id is None:
                cursor = self._connection.execute(
                    """
                    INSERT INTO maintenance_records
                        (train_id, service_date, service_type, description, mileage_km, cost,
                         performed_by, next_service_date, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, values,
                )
                record_id = int(cursor.lastrowid)
            else:
                cursor = self._connection.execute(
                    """
                    UPDATE maintenance_records SET train_id = ?, service_date = ?,
                        service_type = ?, description = ?, mileage_km = ?, cost = ?,
                        performed_by = ?, next_service_date = ?, metadata_json = ?
                    WHERE record_id = ?
                    """, values + (record.record_id,),
                )
                if cursor.rowcount == 0:
                    raise KeyError(f"unknown maintenance record: {record.record_id}")
                record_id = record.record_id
        return replace(record, record_id=record_id)

    create_maintenance_record = upsert_maintenance_record
    add_maintenance_record = upsert_maintenance_record
    update_maintenance_record = upsert_maintenance_record

    def get_maintenance_record(self, record_id: int) -> MaintenanceRecord | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM maintenance_records WHERE record_id = ?", (record_id,)).fetchone()
        return self._maintenance_from_row(row) if row else None

    def list_maintenance_records(self, train_id: str) -> tuple[MaintenanceRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM maintenance_records WHERE train_id = ? ORDER BY service_date DESC, record_id DESC",
                (train_id,),
            ).fetchall()
        return tuple(self._maintenance_from_row(row) for row in rows)

    get_maintenance_records = list_maintenance_records

    def delete_maintenance_record(self, record_id: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM maintenance_records WHERE record_id = ?", (record_id,))
        return cursor.rowcount > 0

    remove_maintenance_record = delete_maintenance_record

    def upsert_rolling_stock(self, record: RollingStockRecord) -> RollingStockRecord:
        self._validate_rolling_stock(record)
        with self._lock, self._connection:
            self._require_train(record.train_id)
            self._connection.execute(
                """
                INSERT INTO rolling_stock_records
                    (train_id, rolling_stock_id, position, vehicle_type, name, manufacturer,
                     model, length_mm, mass_g, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(train_id, rolling_stock_id) DO UPDATE SET
                    position = excluded.position, vehicle_type = excluded.vehicle_type,
                    name = excluded.name, manufacturer = excluded.manufacturer,
                    model = excluded.model, length_mm = excluded.length_mm,
                    mass_g = excluded.mass_g, metadata_json = excluded.metadata_json
                """,
                (record.train_id, record.rolling_stock_id, record.position, record.vehicle_type,
                 record.name, record.manufacturer, record.model, record.length_mm, record.mass_g,
                 _dump_json(record.metadata)),
            )
        return record

    upsert_consist_record = upsert_rolling_stock
    upsert_rolling_stock_record = upsert_rolling_stock
    add_rolling_stock = upsert_rolling_stock
    update_rolling_stock = upsert_rolling_stock

    def get_rolling_stock(self, train_id: str, rolling_stock_id: str) -> RollingStockRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM rolling_stock_records WHERE train_id = ? AND rolling_stock_id = ?",
                (train_id, rolling_stock_id),
            ).fetchone()
        return self._rolling_stock_from_row(row) if row else None

    get_rolling_stock_record = get_rolling_stock

    def list_rolling_stock(self, train_id: str) -> tuple[RollingStockRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM rolling_stock_records WHERE train_id = ? ORDER BY position, rolling_stock_id", (train_id,)
            ).fetchall()
        return tuple(self._rolling_stock_from_row(row) for row in rows)

    list_consist_records = list_rolling_stock
    list_rolling_stock_records = list_rolling_stock
    get_rolling_stock_records = list_rolling_stock

    def delete_rolling_stock(self, train_id: str, rolling_stock_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM rolling_stock_records WHERE train_id = ? AND rolling_stock_id = ?",
                (train_id, rolling_stock_id),
            )
        return cursor.rowcount > 0
    def upsert_inventory(self, record: RollingStockInventoryRecord) -> RollingStockInventoryRecord:
        """Insert or update one inventory row without creating duplicate entries."""

        self._validate_inventory(record)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO rolling_stock_inventory
                    (item_id, name, vehicle_type, quantity, manufacturer, model,
                     length_mm, mass_g, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_id) DO UPDATE SET
                    name = excluded.name, vehicle_type = excluded.vehicle_type,
                    quantity = excluded.quantity, manufacturer = excluded.manufacturer,
                    model = excluded.model, length_mm = excluded.length_mm,
                    mass_g = excluded.mass_g, metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (record.item_id, record.name, record.vehicle_type, record.quantity,
                 record.manufacturer, record.model, record.length_mm, record.mass_g,
                 _dump_json(record.metadata)),
            )
        return record

    upsert_rolling_stock_inventory = upsert_inventory
    upsert_inventory_record = upsert_inventory
    add_inventory = upsert_inventory
    add_rolling_stock_inventory = upsert_inventory

    def get_inventory(self, item_id: str) -> RollingStockInventoryRecord | None:
        """Return one inventory row, or ``None`` when it does not exist."""

        self._validate_inventory_id(item_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM rolling_stock_inventory WHERE item_id = ?", (item_id,)
            ).fetchone()
        return self._inventory_from_row(row) if row else None

    get_rolling_stock_inventory = get_inventory
    get_inventory_record = get_inventory

    def list_inventory(self, *, vehicle_type: str | None = None) -> tuple[RollingStockInventoryRecord, ...]:
        """List inventory rows in deterministic order."""

        with self._lock:
            if vehicle_type is None:
                rows = self._connection.execute(
                    "SELECT * FROM rolling_stock_inventory ORDER BY vehicle_type, name, item_id"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM rolling_stock_inventory WHERE vehicle_type = ? "
                    "ORDER BY vehicle_type, name, item_id", (vehicle_type,)
                ).fetchall()
        return tuple(self._inventory_from_row(row) for row in rows)

    list_rolling_stock_inventory = list_inventory
    list_inventory_records = list_inventory
    get_inventory_records = list_inventory

    def adjust_inventory(self, item_id: str, delta: int, **fields: Any) -> RollingStockInventoryRecord:
        """Add a signed quantity delta, optionally creating a new item with details."""

        self._validate_inventory_id(item_id)
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise ValueError("inventory delta must be an integer")
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM rolling_stock_inventory WHERE item_id = ?", (item_id,)
            ).fetchone()
            current = self._inventory_from_row(row) if row else None
            if current is None:
                if not fields.get("name"):
                    raise KeyError(f"unknown inventory item: {item_id}")
                current = RollingStockInventoryRecord(
                    item_id=item_id, name=str(fields["name"]),
                    vehicle_type=str(fields.get("vehicle_type", "vehicle")), quantity=0,
                    manufacturer=str(fields.get("manufacturer", "")), model=str(fields.get("model", "")),
                    length_mm=fields.get("length_mm"), mass_g=fields.get("mass_g"),
                    metadata=dict(fields.get("metadata", {})),
                )
            quantity = current.quantity + delta
            if quantity < 0:
                raise ValueError("quantity cannot be negative")
            updates = {key: fields[key] for key in
                       ("name", "vehicle_type", "manufacturer", "model", "length_mm", "mass_g", "metadata")
                       if key in fields}
            return self.upsert_inventory(replace(current, quantity=quantity, **updates))

    adjust_inventory_quantity = adjust_inventory
    adjust_rolling_stock_inventory_quantity = adjust_inventory
    adjust_quantity = adjust_inventory
    change_inventory_quantity = adjust_inventory

    def delete_inventory(self, item_id: str) -> bool:
        """Delete one inventory row and report whether it existed."""

        self._validate_inventory_id(item_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM rolling_stock_inventory WHERE item_id = ?", (item_id,)
            )
        return cursor.rowcount > 0

    delete_inventory_record = delete_inventory
    delete_rolling_stock_inventory = delete_inventory
    remove_inventory = delete_inventory

    def add_calibration(
        self,
        train_id: str,
        *,
        speed_kmh: float,
        duration_ms: int,
        measured_distance_mm: float,
        notes: str = "",
        created_at: str,
    ) -> CalibrationRecord:
        """Persist one measured movement and return its assigned ID."""

        if not train_id.strip():
            raise ValueError("train_id is required")
        if speed_kmh <= 0 or duration_ms <= 0 or measured_distance_mm < 0:
            raise ValueError("calibration values must be positive except measured distance")
        with self._lock, self._connection:
            self._require_train(train_id)
            cursor = self._connection.execute(
                """
                INSERT INTO train_calibrations
                    (train_id, speed_kmh, duration_ms, measured_distance_mm, created_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (train_id, float(speed_kmh), int(duration_ms), float(measured_distance_mm), str(created_at), str(notes)),
            )
            calibration_id = int(cursor.lastrowid)
        return CalibrationRecord(calibration_id, train_id, float(speed_kmh), int(duration_ms), float(measured_distance_mm), str(created_at), str(notes))

    def list_calibrations(self, train_id: str | None = None) -> tuple[CalibrationRecord, ...]:
        with self._lock:
            if train_id is None:
                rows = self._connection.execute(
                    "SELECT * FROM train_calibrations ORDER BY created_at DESC, calibration_id DESC"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM train_calibrations WHERE train_id = ? ORDER BY created_at DESC, calibration_id DESC",
                    (train_id,),
                ).fetchall()
        return tuple(self._calibration_from_row(row) for row in rows)

    get_calibrations = list_calibrations

    delete_rolling_stock_record = delete_rolling_stock
    remove_rolling_stock = delete_rolling_stock

    def get_details(self, train_id: str) -> TrainDetails | None:
        train = self.get(train_id)
        if train is None:
            return None
        return TrainDetails(
            train=train,
            decoder_functions=self.list_decoder_functions(train_id),
            maintenance_records=self.list_maintenance_records(train_id),
            rolling_stock=self.list_rolling_stock(train_id),
            calibrations=self.list_calibrations(train_id),
        )

    get_full_train = get_details

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteTrainDatabase":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_train(self, train_id: str) -> None:
        if self._connection.execute("SELECT 1 FROM trains WHERE train_id = ?", (train_id,)).fetchone() is None:
            raise KeyError(f"unknown train: {train_id}")

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {"value": value}

    @classmethod
    def _decoder_function_from_row(cls, row: sqlite3.Row) -> DecoderFunctionMapping:
        return DecoderFunctionMapping(
            train_id=row["train_id"], function_number=row["function_number"], name=row["name"],
            description=row["description"], momentary=bool(row["momentary"]), enabled=bool(row["enabled"]),
            metadata=cls._json_object(row["metadata_json"]),
        )

    @classmethod
    def _maintenance_from_row(cls, row: sqlite3.Row) -> MaintenanceRecord:
        return MaintenanceRecord(
            train_id=row["train_id"], service_date=row["service_date"], service_type=row["service_type"],
            description=row["description"], mileage_km=row["mileage_km"], cost=row["cost"],
            performed_by=row["performed_by"], next_service_date=row["next_service_date"],
            record_id=row["record_id"], metadata=cls._json_object(row["metadata_json"]),
        )

    @classmethod
    def _rolling_stock_from_row(cls, row: sqlite3.Row) -> RollingStockRecord:
        return RollingStockRecord(
            train_id=row["train_id"], rolling_stock_id=row["rolling_stock_id"], position=row["position"],
            vehicle_type=row["vehicle_type"], name=row["name"], manufacturer=row["manufacturer"],
            model=row["model"], length_mm=row["length_mm"], mass_g=row["mass_g"],
            metadata=cls._json_object(row["metadata_json"]),
        )

    @classmethod
    def _inventory_from_row(cls, row: sqlite3.Row) -> RollingStockInventoryRecord:
        return RollingStockInventoryRecord(
            item_id=row["item_id"], name=row["name"], vehicle_type=row["vehicle_type"], quantity=int(row["quantity"]),
            manufacturer=row["manufacturer"], model=row["model"], length_mm=row["length_mm"], mass_g=row["mass_g"],
            metadata=cls._json_object(row["metadata_json"]),
        )


    @classmethod
    def _calibration_from_row(cls, row: sqlite3.Row) -> CalibrationRecord:
        return CalibrationRecord(
            calibration_id=row["calibration_id"], train_id=row["train_id"],
            speed_kmh=row["speed_kmh"], duration_ms=row["duration_ms"],
            measured_distance_mm=row["measured_distance_mm"],
            created_at=row["created_at"], notes=row["notes"],
        )

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> TrainModel:
        return TrainModel(
            train_id=row["train_id"], name=row["name"], manufacturer=row["manufacturer"], model=row["model"],
            scale=row["scale"], decoder_address=row["decoder_address"], decoder_protocol=row["decoder_protocol"],
            era=row["era"], length_mm=row["length_mm"], mass_g=row["mass_g"], max_speed_kmh=row["max_speed_kmh"],
            metadata=cls._json_object(row["metadata_json"]),
        )

    @staticmethod
    def _validate(train: TrainModel) -> None:
        if not train.train_id.strip():
            raise ValueError("train_id is required")
        if not train.name.strip():
            raise ValueError("name is required")
        if train.decoder_address is not None and not 0 <= train.decoder_address <= 0x3FFF:
            raise ValueError("decoder_address must fit the DCC address range")
        for name in ("length_mm", "mass_g", "max_speed_kmh"):
            value = getattr(train, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")

    @staticmethod
    def _validate_decoder_function(mapping: DecoderFunctionMapping) -> None:
        if not mapping.train_id.strip():
            raise ValueError("train_id is required")
        if mapping.function_number < 0:
            raise ValueError("function_number cannot be negative")
        if not mapping.name.strip():
            raise ValueError("decoder function name is required")

    @staticmethod
    def _validate_maintenance_record(record: MaintenanceRecord) -> None:
        if not record.train_id.strip():
            raise ValueError("train_id is required")
        if not record.service_date.strip():
            raise ValueError("service_date is required")
        if not record.service_type.strip():
            raise ValueError("service_type is required")
        for name in ("mileage_km", "cost"):
            value = getattr(record, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


    @staticmethod
    def _validate_rolling_stock(record: RollingStockRecord) -> None:
        if not record.train_id.strip():
            raise ValueError("train_id is required")
        if not record.rolling_stock_id.strip():
            raise ValueError("rolling_stock_id is required")
        if record.position < 0:
            raise ValueError("position cannot be negative")
        for name in ("length_mm", "mass_g"):
            value = getattr(record, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")

    @staticmethod
    def _validate_inventory_id(item_id: str) -> None:
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("item_id is required")

    @classmethod
    def _validate_inventory(cls, record: RollingStockInventoryRecord) -> None:
        if not isinstance(record, RollingStockInventoryRecord):
            raise ValueError("record must be a RollingStockInventoryRecord")
        cls._validate_inventory_id(record.item_id)
        if not isinstance(record.name, str) or not record.name.strip():
            raise ValueError("inventory name is required")
        if isinstance(record.quantity, bool) or not isinstance(record.quantity, int) or record.quantity < 0:
            raise ValueError("inventory quantity must be a non-negative whole number")
        if not isinstance(record.vehicle_type, str) or not record.vehicle_type.strip():
            raise ValueError("vehicle_type is required")
        for name in ("length_mm", "mass_g"):
            value = getattr(record, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if not isinstance(record.metadata, Mapping):
            raise ValueError("metadata must be a mapping")


def _dump_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))
