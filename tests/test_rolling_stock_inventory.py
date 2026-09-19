import tempfile
import unittest
from pathlib import Path

from backend.infrastructure.train_database import RollingStockInventoryRecord, RollingStockRecord, SQLiteTrainDatabase, TrainModel


class RollingStockInventoryTests(unittest.TestCase):
    def test_quantity_is_adjustable_without_duplicate_catalogue_rows(self) -> None:
        database = SQLiteTrainDatabase()
        database.upsert(TrainModel("loco-1", "Locomotive"))
        database.upsert_inventory(RollingStockInventoryRecord("coach-i11", "I11 coach", vehicle_type="coach", quantity=2))
        database.adjust_inventory("coach-i11", 3)
        self.assertEqual(database.get_inventory("coach-i11").quantity, 5)
        self.assertEqual(len(database.list_inventory()), 1)
        database.close()

    def test_inventory_persists_across_database_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trains.sqlite3"
            first = SQLiteTrainDatabase(path)
            first.upsert_inventory(RollingStockInventoryRecord("wagon-1", "Eanos", vehicle_type="wagon", quantity=4))
            first.close()
            second = SQLiteTrainDatabase(path)
            self.assertEqual(second.get_inventory("wagon-1").quantity, 4)
            second.close()

    def test_quantity_cannot_become_negative(self) -> None:
        database = SQLiteTrainDatabase()
        with self.assertRaisesRegex(ValueError, "non-negative"):
            database.upsert_inventory(RollingStockInventoryRecord("coach", "Coach", quantity=-1))
        database.close()

    def test_upsert_replaces_quantity_and_delete_removes_one_catalogue_row(self) -> None:
        database = SQLiteTrainDatabase()
        first = RollingStockInventoryRecord("wagon-1", "Eanos", vehicle_type="wagon", quantity=1)
        changed = RollingStockInventoryRecord("wagon-1", "Eanos", vehicle_type="wagon", quantity=6)
        self.assertEqual(database.upsert_inventory(first), first)
        self.assertEqual(database.upsert_inventory(changed), changed)
        self.assertEqual(database.list_inventory(), (changed,))
        self.assertTrue(database.delete_inventory("wagon-1"))
        self.assertFalse(database.delete_inventory("wagon-1"))
        self.assertEqual(database.list_inventory(), ())
        database.close()

    def test_inventory_is_independent_from_train_and_consist_records(self) -> None:
        database = SQLiteTrainDatabase()
        train = TrainModel("loco-1", "Locomotive")
        database.upsert(train)
        consist = RollingStockRecord("loco-1", "coach-1", position=1, vehicle_type="coach")
        database.upsert_rolling_stock(consist)
        inventory = RollingStockInventoryRecord("coach-1", "Coach", vehicle_type="coach", quantity=2)
        database.upsert_inventory(inventory)
        self.assertEqual(database.get_full_train("loco-1").rolling_stock, (consist,))
        database.delete("loco-1")
        self.assertEqual(database.get_inventory("coach-1"), inventory)
        database.close()

if __name__ == "__main__":
    unittest.main()
