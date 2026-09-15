from dataclasses import dataclass

from backend.services.train_presence import SavedTrainPresenceService


def test_scan_pings_every_saved_locomotive_and_returns_summary():
    calls = []

    def probe(address):
        calls.append(address)
        return {"address": address, "identified": address == 7}

    scan = SavedTrainPresenceService(probe).scan(
        [
            {"train_id": "ice", "dcc_address": 7},
            {"id": "freight", "address": 12},
        ]
    )

    assert calls == [7, 12]
    assert [result.status for result in scan.results] == ["detected", "unknown"]
    assert scan.summary.as_dict() == {
        "total": 2,
        "detected": 1,
        "unknown": 1,
        "errors": 0,
    }


def test_missing_or_negative_probe_response_is_unknown():
    scan = SavedTrainPresenceService(lambda _address: None).scan(
        [
            {"train_id": "unconfigured"},
            {"train_id": "not-there", "dcc_address": 8},
            {"train_id": "invalid", "dcc_address": 0},
        ]
    )

    assert [result.status for result in scan.results] == ["unknown", "unknown", "unknown"]
    assert scan.summary.unknown == 3


def test_explicit_negative_mapping_response_is_unknown():
    scan = SavedTrainPresenceService(lambda _address: {"detected": False}).scan(
        [{"train_id": "not-there", "dcc_address": 8}]
    )

    assert scan.results[0].status == "unknown"
    assert scan.summary.unknown == 1


def test_probe_errors_are_isolated_to_the_affected_train():
    def probe(address):
        if address == 8:
            raise TimeoutError("reply timeout")
        return True

    scan = SavedTrainPresenceService(probe).scan(
        [
            {"train_id": "ok", "dcc_address": 7},
            {"train_id": "offline", "dcc_address": 8},
        ]
    )

    assert scan.results[0].detected is True
    assert scan.results[1].status == "error"
    assert scan.results[1].error == "TimeoutError: reply timeout"
    assert scan.summary.as_dict() == {
        "total": 2,
        "detected": 1,
        "unknown": 0,
        "errors": 1,
    }


@dataclass
class SavedTrain:
    id: str
    dcc_address: int


def test_object_records_and_serialization_are_supported():
    scan = SavedTrainPresenceService(lambda address: {"ok": address == 7}).scan(
        [SavedTrain("locomotive-7", 7)]
    )

    assert scan.as_dict()["results"][0]["train_id"] == "locomotive-7"
    assert scan.as_dict()["summary"]["detected"] == 1
