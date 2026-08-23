"""Opt-in live dashboard verification against ambient Firestore credentials.

Run explicitly; the normal suite never touches production:

    $env:AIRCHIVE_RUN_LIVE_TESTS='1'
    python -m pytest tests/test_dashboard_live.py -q
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from streamlit.testing.v1 import AppTest

from airchive.dashboard.cache import DashboardCache
from airchive.dashboard.config import load_dashboard_config, load_dashboard_dotenv
from airchive.dashboard.repository import DashboardRepository
from airchive.dashboard.service import DashboardService
from airchive.storage.client import build_client

pytestmark = pytest.mark.skipif(
    os.environ.get("AIRCHIVE_RUN_LIVE_TESTS") != "1",
    reason="opt-in live verification only",
)


def live_dashboard_script(service, config, now):
    from airchive.dashboard.app import render_dashboard

    render_dashboard(service, config, now=now)


class CountingRepository:
    def __init__(self, delegate):
        self.delegate = delegate
        self.range_reads = 0
        self.mutation_reads = 0
        self.raw_reads = 0

    def observations_in_range(self, since, until):
        self.range_reads += 1
        return self.delegate.observations_in_range(since, until)

    def observations_changed_since(self, field_path, since):
        self.mutation_reads += 1
        return self.delegate.observations_changed_since(field_path, since)

    def get_health(self):
        return self.delegate.get_health()

    def get_reconciliation(self):
        return self.delegate.get_reconciliation()

    def get_full_observation(self, sample_id):
        self.raw_reads += 1
        return self.delegate.get_full_observation(sample_id)


def firestore_snapshot(client, device_id: str) -> dict:
    root = f"devices/{device_id}"
    telemetry = {
        snapshot.id: snapshot.to_dict()
        for snapshot in client.collection(f"{root}/telemetry").stream()
    }
    health = client.document(f"{root}/runtime/collector").get()
    reconciliation = client.document(f"{root}/runtime/reconciliation").get()
    return {
        "telemetry": telemetry,
        "health": health.to_dict() if health.exists else None,
        "reconciliation": reconciliation.to_dict() if reconciliation.exists else None,
    }


def test_live_dashboard_interactions_reuse_cache_and_write_nothing(tmp_path):
    load_dashboard_dotenv()
    base_config = load_dashboard_config()
    config = replace(base_config, cache_path=tmp_path / "dashboard.sqlite3")
    client = build_client(config.project_id)
    repository = CountingRepository(DashboardRepository(client, config.device_id))
    cache = DashboardCache(config.cache_path)
    service = DashboardService(
        repository,
        cache,
        project_id=config.project_id,
        device_id=config.device_id,
        refresh_seconds=config.refresh_seconds,
    )
    now = datetime.now(UTC)
    before = firestore_snapshot(client, config.device_id)

    app = AppTest.from_function(
        live_dashboard_script,
        args=(service, config, now),
        default_timeout=30,
    ).run()
    assert not app.exception
    assert app.title[0].value == "Airchive"
    assert app.metric
    assert app.dataframe
    assert app.get("vega_lite_chart")
    initial_range_reads = repository.range_reads
    initial_mutation_reads = repository.mutation_reads
    assert initial_range_reads >= 1
    assert initial_mutation_reads == 2

    app.radio[0].set_value("Anomalies").run(timeout=30)
    assert not app.exception
    assert repository.range_reads == initial_range_reads
    assert repository.mutation_reads == initial_mutation_reads

    app.radio[0].set_value("All").run(timeout=30)
    raw_button = next(button for button in app.button if button.label == "Load raw payload")
    raw_button.click().run(timeout=30)
    assert repository.raw_reads == 1

    refresh = next(button for button in app.button if button.label == "Refresh now")
    refresh.click().run(timeout=30)
    assert repository.range_reads == initial_range_reads
    assert repository.mutation_reads == initial_mutation_reads + 2

    after = firestore_snapshot(client, config.device_id)
    assert after == before
