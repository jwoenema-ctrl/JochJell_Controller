from __future__ import annotations

import unittest

from backend.api.server import ControllerApplication


class CatalogueApiTests(unittest.TestCase):
    def test_portable_catalogue_export_contains_full_train_details(self) -> None:
        app = ControllerApplication.sample()
        try:
            payload = app.train_catalogue()
            self.assertEqual(payload["format"], "h0-train-catalogue")
            self.assertEqual(len(payload["trains"]), 2)
            self.assertIn("decoder_functions", payload["trains"][0])
            self.assertIn("maintenance_records", payload["trains"][0])
            self.assertIn("rolling_stock", payload["trains"][0])
        finally:
            app.close()

    def test_portable_catalogue_csv_export_is_available(self) -> None:
        app = ControllerApplication.sample()
        try:
            payload = app.train_catalogue("csv")
            self.assertEqual(payload["format"], "csv")
            self.assertIn("train_id,name", payload["content"])
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
