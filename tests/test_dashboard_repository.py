"""Read-only projection and pagination for the local dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airchive.dashboard.models import ObservationProjection
from airchive.dashboard.repository import PROJECTION_FIELDS, DashboardRepository
from tests.fakes import FakeFirestoreClient

DEVICE = "device-dashboard"
ROOT = f"devices/{DEVICE}"


def instant(minute: int) -> datetime:
    return datetime(2026, 8, 24, 1, minute, tzinfo=UTC)


def document(
    minute: int,
    *,
    persisted_at: datetime | None = None,
    reconciled_at: datetime | None = None,
    completeness: int = 3,
) -> dict:
    observed_at = instant(minute)
    sample_id = observed_at.strftime("%Y%m%dT%H%M%SZ")
    value = float(minute)
    return {
        "sampleId": sample_id,
        "scheduledAt": observed_at,
        "observedAt": observed_at,
        "persistedAt": persisted_at or observed_at,
        "reconciledAt": reconciled_at,
        "localDate": "2026-08-24",
        "timezone": "Asia/Manila",
        "completeness": completeness,
        "energy": {
            "rawDailyTotal": str(value),
            "rawDailyTotalNumber": value,
            "unit": "Wh",
            "intervalValue": "1",
            "intervalValueNumber": 1.0,
            "intervalSeconds": 300,
        },
        "quality": {"intervalStatus": "NORMAL", "flags": []},
        "source": {"energy": {"ok": True}, "state": {"ok": True}},
        "state": {
            "operation": {"airConOperationMode": "POWER_ON", "unused": "omit-me"},
            "temperature": {"targetTemperature": 25, "unit": "C"},
            "unusedGroup": {"large": "omit-me"},
        },
        "raw": {"energy": {"secretSize": "large"}, "state": {"large": True}},
        "collectorVersion": "0.1.1",
    }


def seeded_client(*documents: dict) -> FakeFirestoreClient:
    values = {}
    for item in documents:
        sample_id = item["sampleId"]
        values[f"{ROOT}/telemetry/{sample_id}"] = item
    return FakeFirestoreClient(values)


def test_projection_maps_complete_partial_and_malformed_values():
    complete = ObservationProjection.from_document(document(0), storage_path="path")
    partial = ObservationProjection.from_document(
        {
            "sampleId": "partial",
            "observedAt": "not-an-instant",
            "completeness": "bad",
            "energy": {"intervalValueNumber": "not-a-number"},
            "quality": {"flags": ["DEVICE_OFFLINE", 3]},
            "source": {"energy": {"ok": "yes"}},
            "state": "unexpected",
        }
    )

    assert complete is not None
    assert complete.interval_value_number == 1.0
    assert complete.principal_state == {
        "airConOperationMode": "POWER_ON",
        "targetTemperature": 25,
        "unit": "C",
    }
    assert partial is not None
    assert partial.observed_at is None
    assert partial.completeness is None
    assert partial.interval_value_number is None
    assert partial.flags == ("DEVICE_OFFLINE",)
    assert partial.energy_ok is None
    assert partial.principal_state == {}
    assert ObservationProjection.from_document({"observedAt": instant(0)}) is None


def test_range_query_paginates_and_excludes_raw_projection():
    client = seeded_client(*(document(minute) for minute in range(5)))
    repository = DashboardRepository(client, DEVICE, page_size=2)

    values = repository.observations_in_range(instant(0), instant(4) + timedelta(seconds=1))

    assert [value.sample_id for value in values] == [
        document(minute)["sampleId"] for minute in range(5)
    ]
    assert len(client.reads) == 5
    assert client.query_selections
    assert all("raw" not in fields for _, fields in client.query_selections)
    assert "state.unusedGroup" not in PROJECTION_FIELDS
    assert all("unused" not in value.principal_state for value in values)


def test_incremental_queries_surface_new_upgrade_and_reconciliation():
    baseline = instant(3)
    new = document(3, persisted_at=instant(4))
    upgraded = document(1, persisted_at=instant(5), completeness=3)
    reconciled = document(0, persisted_at=instant(0), reconciled_at=instant(5))
    client = seeded_client(new, upgraded, reconciled)
    repository = DashboardRepository(client, DEVICE, page_size=2)

    persisted = repository.observations_changed_since("persistedAt", baseline)
    patched = repository.observations_changed_since("reconciledAt", baseline)

    assert {value.sample_id for value in persisted} == {
        new["sampleId"],
        upgraded["sampleId"],
    }
    assert [value.sample_id for value in patched] == [reconciled["sampleId"]]


def test_health_reconciliation_and_raw_detail_are_explicit_and_read_only():
    item = document(0)
    sample_id = item["sampleId"]
    client = seeded_client(item)
    client.documents[f"{ROOT}/runtime/collector"] = {
        "lastSuccessAt": instant(0),
        "consecutiveFailures": 0,
    }
    client.documents[f"{ROOT}/runtime/reconciliation"] = {"pending": {sample_id: {}}}
    repository = DashboardRepository(client, DEVICE)

    repository.observations_in_range(instant(0), instant(1))
    assert f"{ROOT}/telemetry/{sample_id}" in client.reads
    projected_reads = len(client.reads)
    assert repository.get_health()["consecutiveFailures"] == 0
    assert sample_id in repository.get_reconciliation()["pending"]
    assert len(client.reads) == projected_reads + 2
    assert repository.get_full_observation(sample_id)["raw"]["state"]["large"] is True
    assert len(client.reads) == projected_reads + 3
    assert client.writes == []


def test_repository_rejects_unsupported_mutation_fields():
    repository = DashboardRepository(FakeFirestoreClient(), DEVICE)

    try:
        repository.observations_changed_since("sampleId", instant(0))
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsupported mutation field was accepted")
