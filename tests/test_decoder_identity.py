"""Protocol-specific decoder IDs survive domain, database and catalogue paths."""

import unittest

from backend.api.domain_bridge import snapshot_from_ui, snapshot_to_ui
from backend.core.models import Train, TrainModelInfo
from backend.infrastructure.train_catalogue import TrainCatalogueRecord, export_csv, export_json, import_csv, import_json
from backend.infrastructure.train_database import SQLiteTrainDatabase, TrainModel


class DecoderIdentityTests(unittest.TestCase):
    def test_ecos_mfx_object_identifier_round_trips_every_storage_boundary(self):
        model = TrainModel("mfx-train", "M4 train", decoder_address=20000, decoder_protocol="mfx")
        database = SQLiteTrainDatabase()
        self.addCleanup(database.close)
        self.assertEqual(database.upsert(model).decoder_protocol, "MFX")
        self.assertEqual(database.get("mfx-train"), model)
        record = TrainCatalogueRecord(train=model)
        self.assertEqual(import_json(export_json([record]))[0].train, model)
        self.assertEqual(import_csv(export_csv([record]))[0].train, model)
        snapshot = snapshot_from_ui(blocks=(), turnouts=(), trains=[
            {"id": "mfx-train", "name": "M4 train", "address": 20000, "decoder_protocol": "mfx"}])
        self.assertEqual(snapshot.trains[0].decoder_address, 20000)
        projected = snapshot_to_ui(snapshot)["trains"][0]
        self.assertEqual(projected["address"], 20000)
        self.assertEqual(projected["decoder_protocol"], "MFX")

    def test_protocol_bounds_reject_wrong_identity_at_domain_and_database(self):
        database = SQLiteTrainDatabase()
        self.addCleanup(database.close)
        for protocol, invalid in (("mm", 256), ("mfx", 65536), ("dcc", 16384)):
            with self.subTest(protocol=protocol):
                with self.assertRaises(ValueError):
                    Train("t", "Train", model=TrainModelInfo(decoder_type=protocol), decoder_address=invalid)
                with self.assertRaises(ValueError):
                    database.upsert(TrainModel("t", "Train", decoder_address=invalid, decoder_protocol=protocol))
        for address in (True, 123.5):
            with self.assertRaises(ValueError):
                Train("t", "Train", decoder_address=address)

    def test_dcc_limits_are_consistent_with_z21_transport(self):
        model = Train("dcc", "DCC", decoder_address=16383)
        self.assertEqual(model.decoder_address, 16383)
        database = SQLiteTrainDatabase()
        self.addCleanup(database.close)
        database.upsert(TrainModel("dcc", "DCC", decoder_address=16383))
        # Older catalogue files allowed the unassigned DCC zero sentinel.
        database.upsert(TrainModel("unassigned", "Unassigned", decoder_address=0))
        with self.assertRaises(ValueError):
            Train("unassigned", "Unassigned", decoder_address=0)

    def test_legacy_z21_lan_and_m4_names_normalize_to_decoder_protocols(self):
        self.assertEqual(TrainModelInfo(decoder_type="Z21 LAN").decoder_type, "DCC")
        self.assertEqual(TrainModel("t", "Train", decoder_protocol="Z21 LAN").decoder_protocol, "DCC")
        self.assertEqual(TrainModel("t", "Train", decoder_protocol="M4").decoder_protocol, "MFX")


if __name__ == "__main__":
    unittest.main()
