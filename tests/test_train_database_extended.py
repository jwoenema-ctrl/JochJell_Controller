"""Focused coverage for the train database's extended model information."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.infrastructure.train_database import (
    DecoderFunctionMapping,
    MaintenanceRecord,
    RollingStockRecord,
    SQLiteTrainDatabase,
    TrainModel,
)


class ExtendedTrainDatabaseTests(unittest.TestCase):
    def test_decoder_functions_are_crud_and_upsert_without_affecting_train(self) -> None:
        with SQLiteTrainDatabase() as database:
            original = database.upsert(TrainModel("T1", "Cargo locomotive", decoder_address=7))
            self.assertEqual(database.upsert(original), original)
            database.upsert_decoder_function(DecoderFunctionMapping("T1", 2, "Horn", momentary=True, metadata={"sound": 2}))
            database.upsert_decoder_function(DecoderFunctionMapping("T1", 0, "Lights"))
            updated = DecoderFunctionMapping("T1", 0, "Headlights", enabled=False)
            self.assertEqual(database.upsert_decoder_function(updated), updated)
            self.assertEqual(database.list_decoder_functions("T1"), (updated, database.get_decoder_function("T1", 2)))
            self.assertEqual(database.get("T1"), original)
            self.assertTrue(database.delete_decoder_function("T1", 2))
            self.assertFalse(database.delete_decoder_function("T1", 2))

    def test_maintenance_records_support_create_update_read_list_delete(self) -> None:
        with SQLiteTrainDatabase() as database:
            database.upsert(TrainModel("T1", "Passenger locomotive"))
            first = database.create_maintenance_record(MaintenanceRecord("T1", "2026-03-12", "inspection", "Routine inspection", mileage_km=42.5))
            second = database.add_maintenance_record(MaintenanceRecord("T1", "2026-04-01", "cleaning", cost=12.0))
            changed = database.update_maintenance_record(MaintenanceRecord("T1", "2026-03-12", "repair", "Replaced coupler", mileage_km=43, record_id=first.record_id))
            self.assertEqual(database.get_maintenance_record(first.record_id), changed)
            self.assertEqual(database.list_maintenance_records("T1"), (second, changed))
            self.assertTrue(database.delete_maintenance_record(second.record_id))
            self.assertIsNone(database.get_maintenance_record(second.record_id))

    def test_rolling_stock_is_ordered_and_upsertable(self) -> None:
        with SQLiteTrainDatabase() as database:
            database.upsert(TrainModel("T1", "Railcar"))
            rear = RollingStockRecord("T1", "R2", position=2, vehicle_type="coach", length_mm=250)
            front = RollingStockRecord("T1", "R1", position=1, vehicle_type="cab", metadata={"photo": "r1.jpg"})
            database.upsert_rolling_stock(rear)
            database.upsert_consist_record(front)
            changed = RollingStockRecord("T1", "R2", position=3, vehicle_type="coach", name="Trailer")
            self.assertEqual(database.upsert_rolling_stock_record(changed), changed)
            self.assertEqual(database.list_consist_records("T1"), (front, changed))
            self.assertEqual(database.get_rolling_stock_record("T1", "R1"), front)
            self.assertTrue(database.delete_rolling_stock_record("T1", "R1"))
            self.assertFalse(database.delete_rolling_stock("T1", "R1"))

    def test_full_details_and_train_delete_cascade_to_metadata(self) -> None:
        with SQLiteTrainDatabase() as database:
            database.upsert(TrainModel("T1", "Complete train", metadata={"photo": "t1.png"}))
            database.upsert_decoder_function(DecoderFunctionMapping("T1", 1, "Bell"))
            maintenance = database.upsert_maintenance_record(MaintenanceRecord("T1", "2026-01-01", "service"))
            database.upsert_rolling_stock(RollingStockRecord("T1", "coach-1"))
            details = database.get_full_train("T1")
            self.assertIsNotNone(details)
            self.assertEqual(details.train.metadata, {"photo": "t1.png"})
            self.assertEqual(len(details.decoder_functions), 1)
            self.assertEqual(details.maintenance_records[0].record_id, maintenance.record_id)
            self.assertEqual(details.rolling_stock[0].rolling_stock_id, "coach-1")
            self.assertTrue(database.delete("T1"))
            self.assertEqual(database.list_decoder_functions("T1"), ())
            self.assertEqual(database.list_maintenance_records("T1"), ())
            self.assertEqual(database.list_rolling_stock("T1"), ())
            self.assertIsNone(database.get_full_train("T1"))

    def test_initialisation_migrates_an_older_trains_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trains.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE trains (train_id TEXT PRIMARY KEY, name TEXT NOT NULL)")
            connection.execute("INSERT INTO trains VALUES ('legacy', 'Legacy train')")
            connection.commit()
            connection.close()
            with SQLiteTrainDatabase(path) as database:
                self.assertEqual(database.get("legacy").name, "Legacy train")
                database.upsert_decoder_function(DecoderFunctionMapping("legacy", 0, "Lights"))
                self.assertEqual(database.list_decoder_functions("legacy")[0].name, "Lights")
                database.upsert(TrainModel("legacy", "Migrated train", metadata={"migrated": True}))
                self.assertEqual(database.get("legacy").metadata, {"migrated": True})


if __name__ == "__main__":
    unittest.main()
