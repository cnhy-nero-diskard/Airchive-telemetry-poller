"""Dashboard repository/cache integration against the Firestore emulator.

Run with:

    firebase emulators:exec --only firestore --project demo-airchive \
        ".venv/Scripts/python.exe -m pytest tests/test_dashboard_emulator.py"
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from airchive.dashboard.cache import DashboardCache
from airchive.dashboard.repository import DashboardRepository
from airchive.dashboard.service import DashboardService

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"),
    reason="needs the Firestore emulator (FIRESTORE_EMULATOR_HOST)",
)


def observation(at: datetime, *, completeness: int = 3) -> dict:
    sample_id = at.strftime("%Y%m%dT%H%M%SZ")
    return {
        "sampleId": sample_id,
        "scheduledAt": at,
        "observedAt": at,
        "persistedAt": at,
        "localDate": "2026-08-24",
        "timezone": "Asia/Manila",
        "completeness": completeness,
        "energy": {
            "rawDailyTotal": str(at.minute),
            "rawDailyTotalNumber": float(at.minute),
            "unit": "Wh",
            "intervalValue": "1",
            "intervalValueNumber": 1.0,
            "intervalSeconds": 300,
        },
        "quality": {"intervalStatus": "NORMAL", "flags": []},
        "source": {"energy": {"ok": True}, "state": {"ok": True}},
        "state": {
            "operation": {"airConOperationMode": "POWER_ON", "unused": "not projected"},
            "temperature": {"targetTemperature": 25, "unit": "C"},
        },
        "raw": {"energy": {"large": "payload"}, "state": {"large": "payload"}},
        "collectorVersion": "0.1.1",
    }


def collection_snapshot(client, collection_path: str) -> dict[str, dict]:
    return {
        snapshot.id: snapshot.to_dict()
        for snapshot in client.collection(collection_path).stream()
    }


def test_dashboard_pagination_mutation_sync_raw_on_demand_and_zero_writes(tmp_path):
    from google.cloud import firestore

    project_id = os.environ.get("GCLOUD_PROJECT", "demo-airchive")
    client = firestore.Client(project=project_id)
    device_id = f"dashboard-{uuid.uuid4().hex[:10]}"
    collection_path = f"devices/{device_id}/telemetry"
    base = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)

    seeded = []
    for offset in range(5):
        item = observation(base + timedelta(minutes=offset))
        client.collection(collection_path).document(item["sampleId"]).set(item)
        seeded.append(item)
    client.document(f"devices/{device_id}/runtime/collector").set(
        {"lastSuccessAt": base + timedelta(minutes=4), "consecutiveFailures": 0}
    )
    client.document(f"devices/{device_id}/runtime/reconciliation").set({"pending": {}})

    repository = DashboardRepository(client, device_id, page_size=2)
    cache = DashboardCache(tmp_path / "dashboard.sqlite3")
    service = DashboardService(
        repository,
        cache,
        project_id=project_id,
        device_id=device_id,
        refresh_seconds=300,
    )

    first_now = base + timedelta(minutes=30)
    values, initial = service.load_range(base, first_now, now=first_now)
    assert initial.succeeded
    assert [value.sample_id for value in values] == [item["sampleId"] for item in seeded]
    assert all("large" not in value.principal_state for value in values)

    mutation_time = first_now + timedelta(minutes=1)
    upgraded_id = seeded[1]["sampleId"]
    reconciled_id = seeded[0]["sampleId"]
    client.collection(collection_path).document(upgraded_id).update(
        {"completeness": 3, "persistedAt": mutation_time}
    )
    client.collection(collection_path).document(reconciled_id).update(
        {
            "reconciledAt": mutation_time,
            "quality.intervalStatus": "DAY_ROLLOVER_RESOLVED",
            "quality.flags": ["RECONCILED"],
        }
    )
    new_item = observation(base + timedelta(minutes=31))
    new_item["persistedAt"] = mutation_time
    client.collection(collection_path).document(new_item["sampleId"]).set(new_item)

    before_reads = collection_snapshot(client, collection_path)
    refreshed = service.refresh(now=mutation_time + timedelta(minutes=1), force=True)
    assert refreshed.succeeded
    cached = cache.observations(
        project_id,
        device_id,
        base,
        mutation_time + timedelta(minutes=2),
    )
    by_id = {value.sample_id: value for value in cached}
    assert new_item["sampleId"] in by_id
    assert by_id[reconciled_id].interval_status == "DAY_ROLLOVER_RESOLVED"
    assert "RECONCILED" in by_id[reconciled_id].flags

    assert service.raw_observation(upgraded_id, now=mutation_time)["raw"]["energy"] == {
        "large": "payload"
    }
    after_reads = collection_snapshot(client, collection_path)
    assert after_reads == before_reads
