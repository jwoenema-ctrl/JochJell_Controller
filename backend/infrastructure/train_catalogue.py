"""Portable import/export for the train database model.

The catalogue format deliberately lives beside, rather than inside, the database
repository.  It can therefore be used by command-line tools, migration scripts,
or another UI without coupling those consumers to SQLite.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO

from .train_database import (
    DecoderFunctionMapping,
    MaintenanceRecord,
    RollingStockRecord,
    SQLiteTrainDatabase,
    TrainDetails,
    TrainModel,
)


CATALOGUE_FORMAT = "h0-train-catalogue"
CATALOGUE_VERSION = 1
DCC_ADDRESS_MIN = 0
DCC_ADDRESS_MAX = 0x3FFF


class CatalogueValidationError(ValueError):
    """Raised when an imported catalogue record is not safe to persist."""


class CatalogueConflictError(ValueError):
    """Raised when a catalogue record would overwrite an existing train."""


@dataclass(frozen=True)
class TrainCatalogueRecord:
    """A portable train model and its optional persisted detail records."""

    train: TrainModel
    decoder_functions: tuple[DecoderFunctionMapping, ...] = ()
    maintenance_records: tuple[MaintenanceRecord, ...] = ()
    rolling_stock: tuple[RollingStockRecord, ...] = ()

    @classmethod
    def from_details(cls, details: TrainDetails) -> "TrainCatalogueRecord":
        return cls(
            train=details.train,
            decoder_functions=tuple(details.decoder_functions),
            maintenance_records=tuple(details.maintenance_records),
            rolling_stock=tuple(details.rolling_stock),
        )

    @classmethod
    def from_train(cls, train: TrainModel) -> "TrainCatalogueRecord":
        return cls(train=train)

    @property
    def train_id(self) -> str:
        return self.train.train_id

    @property
    def name(self) -> str:
        return self.train.name

    def to_details(self) -> TrainDetails:
        """Return the database model equivalent of this catalogue record."""

        return TrainDetails(
            train=self.train,
            decoder_functions=self.decoder_functions,
            maintenance_records=self.maintenance_records,
            rolling_stock=self.rolling_stock,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return the stable, JSON-compatible representation of this record."""

        train = self.train
        return {
            "train_id": train.train_id,
            "name": train.name,
            "manufacturer": train.manufacturer,
            "model": train.model,
            "scale": train.scale,
            "decoder_address": train.decoder_address,
            "decoder_protocol": train.decoder_protocol,
            "era": train.era,
            "length_mm": train.length_mm,
            "mass_g": train.mass_g,
            "max_speed_kmh": train.max_speed_kmh,
            "metadata": dict(train.metadata),
            "decoder_functions": [
                {
                    "function_number": item.function_number,
                    "name": item.name,
                    "description": item.description,
                    "momentary": item.momentary,
                    "enabled": item.enabled,
                    "metadata": dict(item.metadata),
                }
                for item in self.decoder_functions
            ],
            "maintenance_records": [
                {
                    "service_date": item.service_date,
                    "service_type": item.service_type,
                    "description": item.description,
                    "mileage_km": item.mileage_km,
                    "cost": item.cost,
                    "performed_by": item.performed_by,
                    "next_service_date": item.next_service_date,
                    "metadata": dict(item.metadata),
                }
                for item in self.maintenance_records
            ],
            "rolling_stock": [
                {
                    "rolling_stock_id": item.rolling_stock_id,
                    "position": item.position,
                    "vehicle_type": item.vehicle_type,
                    "name": item.name,
                    "manufacturer": item.manufacturer,
                    "model": item.model,
                    "length_mm": item.length_mm,
                    "mass_g": item.mass_g,
                    "metadata": dict(item.metadata),
                }
                for item in self.rolling_stock
            ],
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TrainCatalogueRecord":
        """Build and validate a record from a JSON/CSV-style mapping."""

        if not isinstance(payload, Mapping):
            raise CatalogueValidationError("each catalogue record must be an object")
        train_payload = payload.get("train", payload)
        if not isinstance(train_payload, Mapping):
            raise CatalogueValidationError("train must be an object")

        try:
            train = TrainModel(
                train_id=_required_text(train_payload, "train_id"),
                name=_required_text(train_payload, "name"),
                manufacturer=_text(train_payload.get("manufacturer", ""), "manufacturer"),
                model=_text(train_payload.get("model", ""), "model"),
                scale=_text(train_payload.get("scale", "H0"), "scale"),
                decoder_address=_optional_int(train_payload.get("decoder_address"), "decoder_address"),
                decoder_protocol=_text(train_payload.get("decoder_protocol", "DCC"), "decoder_protocol"),
                era=_text(train_payload.get("era", ""), "era"),
                length_mm=_optional_float(train_payload.get("length_mm"), "length_mm"),
                mass_g=_optional_float(train_payload.get("mass_g"), "mass_g"),
                max_speed_kmh=_optional_float(train_payload.get("max_speed_kmh"), "max_speed_kmh"),
                metadata=_mapping(train_payload.get("metadata", {}), "metadata"),
            )
            record = cls(
                train=train,
                decoder_functions=tuple(
                    _decoder_function(train.train_id, item)
                    for item in _list_value(payload, "decoder_functions")
                ),
                maintenance_records=tuple(
                    _maintenance_record(train.train_id, item)
                    for item in _list_value(payload, "maintenance_records")
                ),
                rolling_stock=tuple(
                    _rolling_stock(train.train_id, item)
                    for item in _list_value(payload, "rolling_stock", fallback="consist")
                ),
            )
        except CatalogueValidationError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CatalogueValidationError(str(exc)) from exc
        validate_record(record)
        return record


@dataclass(frozen=True)
class CatalogueMergeResult:
    """IDs affected by a successful merge."""

    imported_ids: tuple[str, ...] = ()
    updated_ids: tuple[str, ...] = ()
    skipped_ids: tuple[str, ...] = ()


class TrainCatalogue:
    """A validated collection of portable train records."""

    def __init__(self, records: Iterable[TrainCatalogueRecord | TrainModel | TrainDetails | Mapping[str, Any]] = ()) -> None:
        normalized: list[TrainCatalogueRecord] = []
        for item in records:
            if isinstance(item, TrainCatalogueRecord):
                record = item
            elif isinstance(item, TrainDetails):
                record = TrainCatalogueRecord.from_details(item)
            elif isinstance(item, TrainModel):
                record = TrainCatalogueRecord.from_train(item)
            elif isinstance(item, Mapping):
                record = TrainCatalogueRecord.from_mapping(item)
            else:
                raise CatalogueValidationError(f"unsupported catalogue record type: {type(item).__name__}")
            validate_record(record)
            normalized.append(record)
        self.records = tuple(normalized)
        self.validate()

    def __iter__(self):
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def validate(self) -> None:
        """Validate all records and reject duplicate train IDs."""

        seen: set[str] = set()
        for record in self.records:
            validate_record(record)
            if record.train_id in seen:
                raise CatalogueValidationError(f"duplicate train_id: {record.train_id}")
            seen.add(record.train_id)

    def to_json(self, *, indent: int | None = 2) -> str:
        return export_json(self.records, indent=indent)

    def to_csv(self) -> str:
        return export_csv(self.records)

    @classmethod
    def from_json(cls, source: str | Path | TextIO) -> "TrainCatalogue":
        return cls(import_json(source))

    @classmethod
    def from_csv(cls, source: str | Path | TextIO) -> "TrainCatalogue":
        return cls(import_csv(source))

    def merge_into(
        self,
        database: SQLiteTrainDatabase,
        *,
        on_conflict: str = "error",
    ) -> CatalogueMergeResult:
        """Merge into a database without silently overwriting existing trains.

        ``error`` is the default and performs a complete conflict preflight
        before any write.  ``skip`` leaves existing train IDs untouched.
        ``replace`` (also accepted as ``update``) explicitly replaces the base
        model and upserts supplied detail rows; it never deletes database rows.
        Maintenance record IDs are intentionally discarded because SQLite IDs
        are local to a database and are not portable catalogue identity.
        """

        self.validate()
        policy = on_conflict.strip().lower()
        if policy == "update":
            policy = "replace"
        if policy not in {"error", "skip", "replace"}:
            raise ValueError("on_conflict must be 'error', 'skip', or 'replace'")

        existing = {record.train_id for record in self.records if database.get(record.train_id) is not None}
        if policy == "error" and existing:
            conflicting = ", ".join(sorted(existing))
            raise CatalogueConflictError(f"train IDs already exist: {conflicting}")

        imported: list[str] = []
        updated: list[str] = []
        skipped: list[str] = []
        for record in self.records:
            if record.train_id in existing and policy == "skip":
                skipped.append(record.train_id)
                continue
            if record.train_id in existing:
                updated.append(record.train_id)
            else:
                imported.append(record.train_id)
            database.upsert(record.train)
            for mapping in record.decoder_functions:
                database.upsert_decoder_function(mapping)
            for maintenance in record.maintenance_records:
                database.upsert_maintenance_record(replace(maintenance, record_id=None))
            for rolling_stock in record.rolling_stock:
                database.upsert_rolling_stock(rolling_stock)
        return CatalogueMergeResult(tuple(imported), tuple(updated), tuple(skipped))


def validate_record(record: TrainCatalogueRecord) -> None:
    """Validate one record using the same constraints as the database model."""

    if not isinstance(record, TrainCatalogueRecord):
        raise CatalogueValidationError("record must be a TrainCatalogueRecord")
    try:
        if not isinstance(record.train.train_id, str) or not isinstance(record.train.name, str):
            raise CatalogueValidationError("train_id and name must be text")
        if isinstance(record.train.decoder_address, bool):
            raise CatalogueValidationError("decoder_address must be an integer")
        if record.train.decoder_address is not None and not isinstance(record.train.decoder_address, int):
            raise CatalogueValidationError("decoder_address must be an integer")
        SQLiteTrainDatabase._validate(record.train)
        for mapping in record.decoder_functions:
            if mapping.train_id != record.train_id:
                raise CatalogueValidationError("decoder function train_id does not match its train")
            SQLiteTrainDatabase._validate_decoder_function(mapping)
        function_numbers = [item.function_number for item in record.decoder_functions]
        if len(function_numbers) != len(set(function_numbers)):
            raise CatalogueValidationError(f"duplicate decoder function for train: {record.train_id}")
        for maintenance in record.maintenance_records:
            if maintenance.train_id != record.train_id:
                raise CatalogueValidationError("maintenance record train_id does not match its train")
            SQLiteTrainDatabase._validate_maintenance_record(maintenance)
        for rolling_stock in record.rolling_stock:
            if rolling_stock.train_id != record.train_id:
                raise CatalogueValidationError("rolling stock train_id does not match its train")
            SQLiteTrainDatabase._validate_rolling_stock(rolling_stock)
        rolling_ids = [item.rolling_stock_id for item in record.rolling_stock]
        if len(rolling_ids) != len(set(rolling_ids)):
            raise CatalogueValidationError(f"duplicate rolling stock for train: {record.train_id}")
        json.dumps(record.to_mapping(), sort_keys=True)
    except CatalogueValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise CatalogueValidationError(str(exc)) from exc


def export_json(
    records: Iterable[TrainCatalogueRecord | TrainModel | TrainDetails | Mapping[str, Any]],
    destination: str | Path | None = None,
    *,
    indent: int | None = 2,
) -> str:
    """Serialize records to a versioned JSON document, optionally saving it."""

    catalogue = records if isinstance(records, TrainCatalogue) else TrainCatalogue(records)
    payload = {
        "format": CATALOGUE_FORMAT,
        "version": CATALOGUE_VERSION,
        "trains": [record.to_mapping() for record in catalogue],
    }
    text = json.dumps(payload, indent=indent, sort_keys=False) + "\n"
    if destination is not None:
        Path(destination).write_text(text, encoding="utf-8")
    return text


def import_json(source: str | Path | TextIO) -> tuple[TrainCatalogueRecord, ...]:
    """Read a versioned JSON catalogue or a bare list of record objects."""

    raw = _read_text(source)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogueValidationError(f"invalid catalogue JSON: {exc.msg}") from exc
    if isinstance(payload, Mapping):
        if payload.get("format", CATALOGUE_FORMAT) != CATALOGUE_FORMAT:
            raise CatalogueValidationError("unsupported catalogue format")
        if payload.get("version", CATALOGUE_VERSION) != CATALOGUE_VERSION:
            raise CatalogueValidationError("unsupported catalogue version")
        payload = payload.get("trains", [])
    if not isinstance(payload, list):
        raise CatalogueValidationError("catalogue JSON must contain a trains list")
    return tuple(TrainCatalogueRecord.from_mapping(item) for item in payload)


_CSV_FIELDS = (
    "train_id",
    "name",
    "manufacturer",
    "model",
    "scale",
    "decoder_address",
    "decoder_protocol",
    "era",
    "length_mm",
    "mass_g",
    "max_speed_kmh",
    "metadata_json",
    "decoder_functions_json",
    "maintenance_records_json",
    "rolling_stock_json",
)


def export_csv(
    records: Iterable[TrainCatalogueRecord | TrainModel | TrainDetails | Mapping[str, Any]],
    destination: str | Path | None = None,
) -> str:
    """Serialize one train per CSV row, including portable detail columns."""

    catalogue = records if isinstance(records, TrainCatalogue) else TrainCatalogue(records)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in catalogue:
        payload = record.to_mapping()
        writer.writerow(
            {
                "train_id": payload["train_id"],
                "name": payload["name"],
                "manufacturer": payload["manufacturer"],
                "model": payload["model"],
                "scale": payload["scale"],
                "decoder_address": _csv_scalar(payload["decoder_address"]),
                "decoder_protocol": payload["decoder_protocol"],
                "era": payload["era"],
                "length_mm": _csv_scalar(payload["length_mm"]),
                "mass_g": _csv_scalar(payload["mass_g"]),
                "max_speed_kmh": _csv_scalar(payload["max_speed_kmh"]),
                "metadata_json": json.dumps(payload["metadata"], sort_keys=True, separators=(",", ":")),
                "decoder_functions_json": json.dumps(payload["decoder_functions"], sort_keys=True, separators=(",", ":")),
                "maintenance_records_json": json.dumps(payload["maintenance_records"], sort_keys=True, separators=(",", ":")),
                "rolling_stock_json": json.dumps(payload["rolling_stock"], sort_keys=True, separators=(",", ":")),
            }
        )
    text = output.getvalue()
    if destination is not None:
        Path(destination).write_text(text, encoding="utf-8", newline="")
    return text


def import_csv(source: str | Path | TextIO) -> tuple[TrainCatalogueRecord, ...]:
    """Read the one-train-per-row CSV representation."""

    reader = csv.DictReader(io.StringIO(_read_text(source)))
    if reader.fieldnames is None or not {"train_id", "name"}.issubset(reader.fieldnames):
        raise CatalogueValidationError("catalogue CSV requires train_id and name columns")
    records: list[TrainCatalogueRecord] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            payload: dict[str, Any] = dict(row)
            payload["decoder_address"] = _csv_optional(row.get("decoder_address"), "decoder_address")
            for field in ("length_mm", "mass_g", "max_speed_kmh"):
                payload[field] = _csv_optional_float(row.get(field), field)
            payload["metadata"] = _csv_json_object(row.get("metadata_json"), "metadata_json")
            payload["decoder_functions"] = _csv_json_list(row.get("decoder_functions_json"), "decoder_functions_json")
            payload["maintenance_records"] = _csv_json_list(row.get("maintenance_records_json"), "maintenance_records_json")
            payload["rolling_stock"] = _csv_json_list(row.get("rolling_stock_json"), "rolling_stock_json")
            records.append(TrainCatalogueRecord.from_mapping(payload))
        except CatalogueValidationError as exc:
            raise CatalogueValidationError(f"CSV row {row_number}: {exc}") from exc
    TrainCatalogue(records).validate()
    return tuple(records)


def _read_text(source: str | Path | TextIO) -> str:
    if hasattr(source, "read"):
        return str(source.read())
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith("{") or stripped.startswith("[") or "\n" in source:
            return source
        return Path(source).read_text(encoding="utf-8")
    return Path(source).read_text(encoding="utf-8")


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    if field not in payload:
        raise CatalogueValidationError(f"{field} is required")
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise CatalogueValidationError(f"{field} is required")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise CatalogueValidationError(f"{field} must be text")
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogueValidationError(f"{field} must be an object")
    return dict(value)


def _optional_int(value: Any, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise CatalogueValidationError(f"{field} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        parsed = int(value.strip())
    else:
        raise CatalogueValidationError(f"{field} must be an integer")
    if not DCC_ADDRESS_MIN <= parsed <= DCC_ADDRESS_MAX:
        raise CatalogueValidationError(
            f"{field} must be between {DCC_ADDRESS_MIN} and {DCC_ADDRESS_MAX}"
        )
    return parsed


def _optional_float(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise CatalogueValidationError(f"{field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CatalogueValidationError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise CatalogueValidationError(f"{field} must be finite")
    return parsed


def _list_value(payload: Mapping[str, Any], field: str, *, fallback: str | None = None) -> list[Any]:
    value = payload.get(field)
    if value is None and fallback:
        value = payload.get(fallback)
    if value is None:
        return []
    if not isinstance(value, list):
        raise CatalogueValidationError(f"{field} must be a list")
    return value


def _decoder_function(train_id: str, payload: Any) -> DecoderFunctionMapping:
    if not isinstance(payload, Mapping):
        raise CatalogueValidationError("decoder function must be an object")
    return DecoderFunctionMapping(
        train_id=train_id,
        function_number=_nonnegative_int(payload.get("function_number"), "function_number"),
        name=_required_text(payload, "name"),
        description=_text(payload.get("description", ""), "description"),
        momentary=_bool(payload.get("momentary", False), "momentary"),
        enabled=_bool(payload.get("enabled", True), "enabled"),
        metadata=_mapping(payload.get("metadata", {}), "metadata"),
    )


def _maintenance_record(train_id: str, payload: Any) -> MaintenanceRecord:
    if not isinstance(payload, Mapping):
        raise CatalogueValidationError("maintenance record must be an object")
    record_id = payload.get("record_id")
    if record_id not in (None, ""):
        record_id = _nonnegative_int(record_id, "record_id")
    return MaintenanceRecord(
        train_id=train_id,
        service_date=_required_text(payload, "service_date"),
        service_type=_required_text(payload, "service_type"),
        description=_text(payload.get("description", ""), "description"),
        mileage_km=_optional_float(payload.get("mileage_km"), "mileage_km"),
        cost=_optional_float(payload.get("cost"), "cost"),
        performed_by=_text(payload.get("performed_by", ""), "performed_by"),
        next_service_date=_optional_text(payload.get("next_service_date"), "next_service_date"),
        record_id=record_id,
        metadata=_mapping(payload.get("metadata", {}), "metadata"),
    )


def _rolling_stock(train_id: str, payload: Any) -> RollingStockRecord:
    if not isinstance(payload, Mapping):
        raise CatalogueValidationError("rolling stock must be an object")
    return RollingStockRecord(
        train_id=train_id,
        rolling_stock_id=_required_text(payload, "rolling_stock_id"),
        position=_nonnegative_int(payload.get("position", 0), "position"),
        vehicle_type=_text(payload.get("vehicle_type", "vehicle"), "vehicle_type"),
        name=_text(payload.get("name", ""), "name"),
        manufacturer=_text(payload.get("manufacturer", ""), "manufacturer"),
        model=_text(payload.get("model", ""), "model"),
        length_mm=_optional_float(payload.get("length_mm"), "length_mm"),
        mass_g=_optional_float(payload.get("mass_g"), "mass_g"),
        metadata=_mapping(payload.get("metadata", {}), "metadata"),
    )


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise CatalogueValidationError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CatalogueValidationError(f"{field} must be a non-negative integer") from exc
    if parsed < 0 or (isinstance(value, float) and value != parsed):
        raise CatalogueValidationError(f"{field} must be a non-negative integer")
    return parsed


def _optional_text(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, field)


def _bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
        return False
    raise CatalogueValidationError(f"{field} must be boolean")


def _csv_scalar(value: Any) -> str:
    return "" if value is None else str(value)


def _csv_optional(value: str | None, field: str) -> int | None:
    return _optional_int(value, field)


def _csv_optional_float(value: str | None, field: str) -> float | None:
    return _optional_float(value, field)


def _csv_json_object(value: str | None, field: str) -> Mapping[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CatalogueValidationError(f"{field} must contain valid JSON") from exc
    return _mapping(parsed, field)


def _csv_json_list(value: str | None, field: str) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CatalogueValidationError(f"{field} must contain valid JSON") from exc
    if not isinstance(parsed, list):
        raise CatalogueValidationError(f"{field} must contain a JSON list")
    return parsed


__all__ = [
    "CATALOGUE_FORMAT",
    "CATALOGUE_VERSION",
    "CatalogueConflictError",
    "CatalogueMergeResult",
    "CatalogueValidationError",
    "DCC_ADDRESS_MAX",
    "DCC_ADDRESS_MIN",
    "TrainCatalogue",
    "TrainCatalogueRecord",
    "export_csv",
    "export_json",
    "import_csv",
    "import_json",
    "validate_record",
]
