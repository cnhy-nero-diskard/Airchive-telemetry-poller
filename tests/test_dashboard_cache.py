"""SQLite projection cache and incremental dashboard synchronization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from airchive.dashboard.cache import DashboardCache, SyncState
from airchive.dashboard.models import ObservationProjection
from airchive.dashboard.presentation import (
    build_overview,
    chart_rows,
    is_anomalous,
    summarize_range,
)
from airchive.dashboard.service import DashboardService
from airchive.redaction import clear_secrets, register_secret

PROJECT = "project-1"
DEVICE = "device-1"
SENTINEL = "SENTINEL-CACHE-SECRET-91d5fca0"


def instant(minute: int) -> datetime:
    return datetime(2026, 8, 24, 1, minute, tzinfo=UTC)


def projection(
    minute: int,
    *,
    interval: float | None = 1.0,
    status: str = "NORMAL",
    flags: list[str] | None = None,
    completeness: int = 3,
    reconciled_at: datetime | None = None,
) -> ObservationProjection:
    observed_at = instant(minute)
    value = ObservationProjection.from_document(
        {
            "sampleId": observed_at.strftime("%Y%m%dT%H%M%SZ"),
            "scheduledAt": observed_at,
            "observedAt": observed_at,
            "persistedAt": observed_at,
            "reconciledAt": reconciled_at,
            "localDate": "2026-08-24",
            "timezone": "Asia/Manila",
            "completeness": completeness,
            "energy": {
                "rawDailyTotal": str(minute),
                "rawDailyTotalNumber": float(minute),
                "unit": "Wh",
                "intervalValue": str(interval) if interval is not None else None,
                "intervalValueNumber": interval,
                "intervalSeconds": 300,
            },
            "quality": {"intervalStatus": status, "flags": flags or []},
            "source": {"energy": {"ok": True}, "state": {"ok": True}},
            "state": {"operation": {"airConOperationMode": "POWER_ON"}},
            "raw": {"mustNotPersist": SENTINEL},
        },
        storage_path=f"devices/{DEVICE}/telemetry/sample-{minute}",
    )
    assert value is not None
    return value


class StubRepository:
    def __init__(self):
        self.range_values: list[ObservationProjection] = []
        self.changed: dict[str, list[ObservationProjection]] = {
            "persistedAt": [],
            "reconciledAt": [],
        }
        self.range_calls: list[tuple[datetime, datetime]] = []
        self.changed_calls: list[tuple[str, datetime]] = []
        self.health = {"consecutiveFailures": 0, "lastSuccessAt": instant(0)}
        self.reconciliation = {"pending": {}}
        self.raw = {"raw": {"state": "full"}}
        self.raw_calls = 0
        self.range_error: Exception | None = None
        self.changed_error: Exception | None = None

    def observations_in_range(self, since, until):
        self.range_calls.append((since, until))
        if self.range_error is not None:
            error, self.range_error = self.range_error, None
            raise error
        return [value for value in self.range_values if since <= value.observed_at < until]

    def observations_changed_since(self, field_path, since):
        self.changed_calls.append((field_path, since))
        if self.changed_error is not None:
            error, self.changed_error = self.changed_error, None
            raise error
        return list(self.changed[field_path])

    def get_health(self):
        return self.health

    def get_reconciliation(self):
        return self.reconciliation

    def get_full_observation(self, sample_id):
        self.raw_calls += 1
        return self.raw


def make_service(tmp_path: Path, repository: StubRepository | None = None):
    cache = DashboardCache(tmp_path / "dashboard.sqlite3")
    repo = repository or StubRepository()
    service = DashboardService(
        repo,
        cache,
        project_id=PROJECT,
        device_id=DEVICE,
        refresh_seconds=300,
    )
    return service, repo, cache


def test_cache_initializes_idempotently_and_scopes_projects_and_devices(tmp_path):
    path = tmp_path / "dashboard.sqlite3"
    first = DashboardCache(path)
    first.upsert_observations(PROJECT, DEVICE, [projection(0)])
    first.upsert_observations("project-2", DEVICE, [projection(1)])
    first.close()

    reopened = DashboardCache(path)
    assert reopened.observation_count(PROJECT, DEVICE) == 1
    assert reopened.observation_count("project-2", DEVICE) == 1
    assert reopened.observation_count(PROJECT, "other-device") == 0


def test_upsert_replaces_projection_and_queries_in_both_orders(tmp_path):
    cache = DashboardCache(tmp_path / "dashboard.sqlite3")
    original = projection(0, completeness=1)
    upgraded = projection(0, completeness=3)
    cache.upsert_observations(PROJECT, DEVICE, [original, projection(1)])
    cache.upsert_observations(PROJECT, DEVICE, [upgraded])

    ascending = cache.observations(PROJECT, DEVICE, instant(0), instant(2))
    descending = cache.observations(
        PROJECT, DEVICE, instant(0), instant(2), descending=True
    )

    assert [value.completeness for value in ascending] == [3, 3]
    assert [value.sample_id for value in descending] == list(
        reversed([value.sample_id for value in ascending])
    )


def test_covered_ranges_return_only_gaps(tmp_path):
    cache = DashboardCache(tmp_path / "dashboard.sqlite3")
    cache.store_range(PROJECT, DEVICE, instant(0), instant(2), [projection(0)])
    cache.store_range(PROJECT, DEVICE, instant(3), instant(4), [projection(3)])

    assert cache.missing_ranges(PROJECT, DEVICE, instant(0), instant(5)) == [
        (instant(2), instant(3)),
        (instant(4), instant(5)),
    ]


def test_failed_range_fetch_does_not_mark_coverage_and_retry_reuses_cache(tmp_path):
    repository = StubRepository()
    repository.range_values = [projection(0), projection(1)]
    repository.range_error = RuntimeError("temporary")
    service, _, cache = make_service(tmp_path, repository)

    values, failed = service.load_range(instant(0), instant(2), now=instant(5))
    assert values == []
    assert not failed.succeeded
    assert cache.missing_ranges(PROJECT, DEVICE, instant(0), instant(2))

    values, succeeded = service.load_range(instant(0), instant(2), now=instant(6))
    assert len(values) == 2
    assert succeeded.succeeded
    assert cache.missing_ranges(PROJECT, DEVICE, instant(0), instant(2)) == []
    assert len(repository.range_calls) == 2

    service.load_range(instant(0), instant(2), now=instant(7))
    assert len(repository.range_calls) == 2


def test_incremental_sync_merges_updates_and_advances_only_on_success(tmp_path):
    service, repository, cache = make_service(tmp_path)
    repository.changed["persistedAt"] = [projection(1, completeness=3)]
    repository.changed["reconciledAt"] = [
        projection(0, status="DAY_ROLLOVER_RESOLVED", reconciled_at=instant(4))
    ]

    result = service.refresh(now=instant(5), force=True)
    assert result.succeeded
    assert cache.sync_state(PROJECT, DEVICE).watermark == instant(5)
    assert cache.observation_count(PROJECT, DEVICE) == 2
    assert all(call[1] == instant(5) - timedelta(minutes=10) for call in repository.changed_calls)

    repository.changed_error = RuntimeError("Firestore unavailable")
    failed = service.refresh(now=instant(6), force=True)
    state = cache.sync_state(PROJECT, DEVICE)
    assert not failed.succeeded
    assert state.watermark == instant(5)
    assert state.last_attempt_at == instant(6)
    assert state.last_error_class == "RuntimeError"
    assert cache.observation_count(PROJECT, DEVICE) == 2


def test_health_and_reconciliation_are_safely_cached(tmp_path):
    register_secret(SENTINEL)
    try:
        service, repository, cache = make_service(tmp_path)
        repository.health = {
            "lastSuccessAt": instant(0),
            "lastErrorClass": "AUTH_FATAL",
            "lastErrorMessage": f"invalid {SENTINEL}",
            "consecutiveFailures": 2,
            "leaseHolder": SENTINEL,
        }
        repository.reconciliation = {
            "pending": {"sample": {"previousLocalDate": "2026-08-23"}},
            "unexpected": SENTINEL,
        }

        assert service.refresh(now=instant(5), force=True).succeeded
        state = cache.sync_state(PROJECT, DEVICE)
        assert state.health["lastErrorMessage"] == "invalid <redacted>"
        assert "leaseHolder" not in state.health
        assert "unexpected" not in state.reconciliation
    finally:
        clear_secrets()


def test_corrupt_cache_is_backed_up_and_reset_is_local(tmp_path):
    path = tmp_path / "dashboard.sqlite3"
    path.write_bytes(b"not sqlite")

    cache, backup = DashboardCache.open_recovering(path, now=instant(0))
    assert backup is not None and backup.read_bytes() == b"not sqlite"
    cache.upsert_observations(PROJECT, DEVICE, [projection(0)])
    cache.reset()
    assert cache.observation_count(PROJECT, DEVICE) == 0


def test_cache_never_persists_raw_secret_or_exception_text(tmp_path):
    register_secret(SENTINEL)
    path = tmp_path / "dashboard.sqlite3"
    try:
        cache = DashboardCache(path)
        item = projection(0)
        unsafe = item.to_json_value()
        unsafe["principal_state"] = {"unit": SENTINEL}
        scrubbed = ObservationProjection.from_json_value(unsafe)
        cache.upsert_observations(PROJECT, DEVICE, [scrubbed])
        cache.record_sync_failure(
            PROJECT,
            DEVICE,
            attempted_at=instant(1),
            error_class="RuntimeError",
        )
        cache.close()
        payload = path.read_bytes()
        assert SENTINEL.encode() not in payload
        assert b"mustNotPersist" not in payload
        assert b"temporary exception details" not in payload
    finally:
        clear_secrets()


def test_overview_range_and_chart_models_preserve_gaps_and_anomalies(tmp_path):
    service, repository, cache = make_service(tmp_path)
    repository.health = {
        "lastAttemptAt": instant(1),
        "lastSuccessAt": instant(0),
        "consecutiveFailures": 1,
        "lastErrorClass": "AUTH_FATAL",
        "lastErrorMessage": "invalid token",
    }
    repository.reconciliation = {"pending": {"sample": {}}}
    service.refresh(now=instant(5), force=True)
    values = [
        projection(0),
        projection(1, interval=None, status="ENERGY_UNAVAILABLE"),
    ]
    cache.upsert_observations(PROJECT, DEVICE, values)

    overview = build_overview(
        service.latest(), service.state(), now=instant(10), cadence_seconds=300
    )
    summary = summarize_range(
        values, since=instant(0), until=instant(2), cadence_seconds=60
    )
    rows = chart_rows(values, datetime.now().astimezone().tzinfo)

    assert overview.stale
    assert overview.consecutive_failures == 1
    assert overview.pending_reconciliations == 1
    assert summary.total == 1.0
    assert summary.usable_slots == 1
    assert not summary.complete
    assert is_anomalous(values[1])
    assert rows[1]["intervalValue"] is None
    assert rows[1]["anomalous"] is True


def test_raw_detail_is_explicit_short_lived_and_never_persisted(tmp_path):
    service, repository, cache = make_service(tmp_path)
    cache.upsert_observations(PROJECT, DEVICE, [projection(0)])
    assert repository.raw_calls == 0

    assert service.raw_observation("sample", now=instant(1))["raw"]["state"] == "full"
    assert service.raw_observation("sample", now=instant(2))["raw"]["state"] == "full"
    assert repository.raw_calls == 1
    cache.close()
    assert b'"state":"full"' not in (tmp_path / "dashboard.sqlite3").read_bytes()


def test_refresh_is_cadence_aligned_unless_manually_forced(tmp_path):
    service, repository, _ = make_service(tmp_path)

    assert service.refresh(now=instant(0), force=True).performed
    calls_after_startup = list(repository.changed_calls)
    automatic = service.refresh(now=instant(1))
    assert not automatic.performed
    assert repository.changed_calls == calls_after_startup

    manual = service.refresh(now=instant(1), force=True)
    assert manual.performed and manual.succeeded
    assert len(repository.changed_calls) == len(calls_after_startup) + 2


def test_empty_overview_marks_values_unavailable_and_stale():
    overview = build_overview(
        None, SyncState(health={}, reconciliation={}), now=instant(0), cadence_seconds=300
    )

    assert overview.latest is None
    assert overview.latest_age_seconds is None
    assert overview.stale
    assert overview.consecutive_failures == 0
