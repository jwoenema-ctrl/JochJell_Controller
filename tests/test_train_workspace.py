import unittest

from backend.api.server import ControllerApplication


class TrainWorkspaceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = ControllerApplication.sample()

    def tearDown(self) -> None:
        self.app.close()

    def test_state_exposes_inventory_summary(self) -> None:
        inventory = self.app.state()["rollingStockInventory"]
        self.assertIn("total", inventory)
        self.assertIn("distinct", inventory)
        self.assertEqual(inventory["total"], sum(item["count"] for item in inventory["items"]))
        self.assertTrue(all(item["count"] > 0 for item in inventory["items"]))

    def test_programming_request_is_validated_and_not_claimed_as_written(self) -> None:
        state = self.app.command({
            "type": "program_decoder",
            "train_id": "train-101",
            "address": 7,
            "target": "programming_track",
            "cv": 29,
            "value": 32,
        })["programming"]
        self.assertFalse(state["supported"])
        self.assertEqual(state["last_request"]["status"], "validated")
        self.assertEqual(state["last_request"]["address"], 7)

    def test_programming_request_rejects_invalid_cv_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "CV must be between"):
            self.app.command({"type": "program_decoder", "train_id": "train-101", "cv": 0, "value": 3})

    def test_simulation_programs_and_persists_a_new_dcc_address(self) -> None:
        state = self.app.command({
            "type": "program_dcc_address",
            "train_id": "train-101",
            "address": 101,
            "new_address": 7,
            "target": "programming_track",
            "confirm": True,
        })["programming"]
        self.assertTrue(state["supported"])
        self.assertEqual(state["last_address_request"]["status"], "simulation_only")
        train = next(item for item in self.app.state()["trains"] if item["id"] == "t1")
        self.assertEqual(train["number"], "7")

    def test_dcc_address_programming_rejects_duplicate_address(self) -> None:
        with self.assertRaisesRegex(ValueError, "already assigned"):
            self.app.command({
                "type": "program_dcc_address",
                "train_id": "train-101",
                "address": 101,
                "new_address": 3,
                "target": "programming_track",
                "confirm": True,
            })


if __name__ == "__main__":
    unittest.main()
