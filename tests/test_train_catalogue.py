"""Focused tests for the portable train catalogue adapter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.infrastructure import (
    CatalogueConflictError,
    CatalogueValidationError,
    DecoderFunctionMapping,
    MaintenanceRecord,
    RollingStockRecord,
    SQLiteTrainDatabase,
    TrainCatalogue,
    TrainCatalogueRecord,
    TrainModel,
    export_csv,
    export_json,
    import_csv,
    import_json,
)


def sample_record() -> TrainCatalogueRecord:
    return TrainCatalogueRecord(
        train=TrainModel(
            "T-CAT-1",
            "ICE 3",
            manufacturer="Example Rail",
            model="BR 403",
            decoder_address=1234,
            era="VI",
            length_mm=1_200,
            metadata={"photo": "ice3.png", "catalogue": "demo"},
        ),
        decoder_functions=(DecoderFunctionMapping("T-CAT-1", 0, "Headlights"),),
        maintenance_records=(MaintenanceRecord("T-CAT-1", "2026-09-01", "inspection", cost=4.5),),
        rolling_stock=(RollingStockRecord("T-CAT-1", "car-1", position=1, vehicle_type="coach"),),
    )


class TrainCatalogueTests(unittest.TestCase):
    def test_json_round_trip_preserves_full_record_and_supports_file_paths(self) -> None:
        record = sample_record()
        text = export_json([record])
        imported = import_json(text)
        self.assertEqual(imported[0].to_details().train, record.train)
        self.assertEqual(imported[0].train, record.train)
        self.assertEqual(imported[0].decoder_functions, record.decoder_functions)
        self.assertEqual(imported[0].maintenance_records[0].service_type, "inspection")
        self.assertEqual(imported[0].rolling_stock, record.rolling_stock)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trains.json"
            export_json([record], path)
            self.assertEqual(import_json(path)[0].train_id, "T-CAT-1")

    def test_csv_round_trip_preserves_nested_details(self) -> None:
        record = sample_record()
        text = export_csv([record])
        self.assertIn("decoder_functions_json", text)
        imported = import_csv(text)
        self.assertEqual(imported[0].train, record.train)
        self.assertEqual(imported[0].decoder_functions, record.decoder_functions)
        self.assertEqual(imported[0].rolling_stock, record.rolling_stock)

    def test_required_fields_and_dcc_range_are_rejected(self) -> None:
        with self.assertRaisesRegex(CatalogueValidationError, "name is required"):
            import_json(json.dumps({"trains": [{"train_id": "missing-name"}]}))
        with self.assertRaisesRegex(CatalogueValidationError, "between 0 and 16383"):
            import_json(json.dumps({"trains": [{"train_id": "bad", "name": "Bad", "decoder_address": 16384}]}))
        with self.assertRaises(CatalogueValidationError):
            import_json(json.dumps({"trains": [{"train_id": "bad", "name": "Bad", "decoder_address": -1}]}))

    def test_duplicate_ids_and_mismatched_nested_ids_are_rejected(self) -> None:
        payload = {"trains": [
            {"train_id": "same", "name": "One"},
            {"train_id": "same", "name": "Two"},
        ]}
        with self.assertRaisesRegex(CatalogueValidationError, "duplicate train_id"):
            TrainCatalogue.from_json(json.dumps(payload))
        mismatched = TrainCatalogueRecord(
            train=TrainModel("T1", "Train"),
            decoder_functions=(DecoderFunctionMapping("T2", 0, "Lights"),),
        )
        with self.assertRaises(CatalogueValidationError):
            TrainCatalogue([mismatched])

    def test_merge_preflights_conflicts_and_supports_explicit_skip_or_replace(self) -> None:
        record = sample_record()
        with SQLiteTrainDatabase() as database:
            database.upsert(TrainModel("T-CAT-1", "Existing", decoder_address=5))
            with self.assertRaises(CatalogueConflictError):
                TrainCatalogue([record]).merge_into(database)
            self.assertEqual(database.get("T-CAT-1").name, "Existing")

            skipped = TrainCatalogue([record]).merge_into(database, on_conflict="skip")
            self.assertEqual(skipped.skipped_ids, ("T-CAT-1",))
            self.assertEqual(database.get("T-CAT-1").name, "Existing")

            replaced = TrainCatalogue([record]).merge_into(database, on_conflict="replace")
            self.assertEqual(replaced.updated_ids, ("T-CAT-1",))
            self.assertEqual(database.get("T-CAT-1").name, "ICE 3")
            self.assertEqual(database.list_decoder_functions("T-CAT-1")[0].name, "Headlights")
            self.assertEqual(len(database.list_maintenance_records("T-CAT-1")), 1)
            self.assertEqual(database.list_rolling_stock("T-CAT-1")[0].rolling_stock_id, "car-1")

    def test_merge_imports_new_records_and_does_not_reuse_local_maintenance_ids(self) -> None:
        record = TrainCatalogueRecord(
            train=TrainModel("T-CAT-2", "Shunter"),
            maintenance_records=(MaintenanceRecord("T-CAT-2", "2026-01-01", "service", record_id=999),),
        )
        with SQLiteTrainDatabase() as database:
            result = TrainCatalogue([record]).merge_into(database)
            self.assertEqual(result.imported_ids, ("T-CAT-2",))
            imported = database.list_maintenance_records("T-CAT-2")
            self.assertEqual(len(imported), 1)
            self.assertNotEqual(imported[0].record_id, 999)


if __name__ == "__main__":
    unittest.main()
