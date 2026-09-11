from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import unittest

from backend.api.server import ControllerApplication, make_server


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

    def test_catalogue_import_updates_database_and_train_overview(self) -> None:
        app = ControllerApplication.sample()
        try:
            result = app.import_train_catalogue({
                "format": "h0-train-catalogue",
                "version": 1,
                "trains": [{
                    "train_id": "catalogue-new",
                    "name": "Catalogue shunter",
                    "manufacturer": "Roco",
                    "model": "70001",
                    "decoder_address": 77,
                    "length_mm": 180,
                    "max_speed_kmh": 60,
                }],
            })
            self.assertEqual(result["imported"], ["catalogue-new"])
            self.assertEqual(app.train_database("catalogue-new")["decoder_address"], 77)
            self.assertTrue(any(item["id"] == "catalogue-new" for item in app.state()["trains"]))
            self.assertEqual(next(item for item in app.state()["trains"] if item["id"] == "catalogue-new")["mode"], "stopped")
        finally:
            app.close()

    def test_catalogue_import_http_endpoint_returns_result_and_state(self) -> None:
        app = ControllerApplication.sample()
        server = make_server("127.0.0.1", 0, app)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            payload = {
                "format": "json",
                "on_conflict": "error",
                "content": json.dumps({
                    "format": "h0-train-catalogue",
                    "version": 1,
                    "trains": [{"train_id": "http-new", "name": "HTTP imported", "decoder_address": 88}],
                }),
            }
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/train-catalogue",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                self.fail(exc.read().decode("utf-8"))
            self.assertEqual(result["result"]["imported"], ["http-new"])
            self.assertTrue(any(item["id"] == "http-new" for item in result["state"]["trains"]))
        finally:
            server.shutdown()
            server.server_close()
            app.close()


if __name__ == "__main__":
    unittest.main()
