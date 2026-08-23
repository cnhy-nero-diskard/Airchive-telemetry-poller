"""Synchronize Firestore projections into the local dashboard cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from airchive.dashboard.cache import DashboardCache, SyncState
from airchive.dashboard.models import ObservationProjection
from airchive.dashboard.repository import DashboardRepository
from airchive.redaction import scrub_object

DEFAULT_OVERLAP = timedelta(minutes=10)
RAW_CACHE_TTL = timedelta(minutes=5)


@dataclass(frozen=True)
class RefreshResult:
    performed: bool
    succeeded: bool
    error_class: str | None = None


class DashboardService:
    def __init__(
        self,
        repository: DashboardRepository,
        cache: DashboardCache,
        *,
        project_id: str,
        device_id: str,
        refresh_seconds: int = 300,
        overlap: timedelta = DEFAULT_OVERLAP,
    ):
        self.repository = repository
        self.cache = cache
        self.project_id = project_id
        self.device_id = device_id
        self.refresh_seconds = refresh_seconds
        self.overlap = overlap
        self._raw_cache: dict[tuple[str, str, str], tuple[datetime, dict[str, Any] | None]] = {}

    def state(self) -> SyncState:
        return self.cache.sync_state(self.project_id, self.device_id)

    def ensure_range(self, since: datetime, until: datetime) -> None:
        for missing_since, missing_until in self.cache.missing_ranges(
            self.project_id, self.device_id, since, until
        ):
            observations = self.repository.observations_in_range(missing_since, missing_until)
            self.cache.store_range(
                self.project_id,
                self.device_id,
                missing_since,
                missing_until,
                observations,
            )

    def refresh(self, *, now: datetime | None = None, force: bool = False) -> RefreshResult:
        sync_started_at = now or datetime.now(UTC)
        state = self.state()
        if (
            not force
            and state.last_success_at is not None
            and sync_started_at - state.last_success_at
            < timedelta(seconds=self.refresh_seconds)
        ):
            return RefreshResult(performed=False, succeeded=True)

        watermark = state.watermark or sync_started_at
        since = watermark - self.overlap
        try:
            persisted = self.repository.observations_changed_since("persistedAt", since)
            reconciled = self.repository.observations_changed_since("reconciledAt", since)
            merged = {item.sample_id: item for item in persisted}
            merged.update({item.sample_id: item for item in reconciled})
            health = self.repository.get_health()
            reconciliation = self.repository.get_reconciliation()
            self.cache.apply_incremental_sync(
                self.project_id,
                self.device_id,
                merged.values(),
                sync_started_at=sync_started_at,
                health=health,
                reconciliation=reconciliation,
            )
        except Exception as exc:
            error_class = type(exc).__name__
            self.cache.record_sync_failure(
                self.project_id,
                self.device_id,
                attempted_at=sync_started_at,
                error_class=error_class,
            )
            return RefreshResult(performed=True, succeeded=False, error_class=error_class)
        return RefreshResult(performed=True, succeeded=True)

    def load_range(
        self,
        since: datetime,
        until: datetime,
        *,
        now: datetime | None = None,
        force_refresh: bool = False,
    ) -> tuple[list[ObservationProjection], RefreshResult]:
        attempted_at = now or datetime.now(UTC)
        try:
            self.ensure_range(since, until)
        except Exception as exc:
            error_class = type(exc).__name__
            self.cache.record_sync_failure(
                self.project_id,
                self.device_id,
                attempted_at=attempted_at,
                error_class=error_class,
            )
            result = RefreshResult(performed=True, succeeded=False, error_class=error_class)
        else:
            result = self.refresh(now=attempted_at, force=force_refresh)
        return (
            self.cache.observations(self.project_id, self.device_id, since, until),
            result,
        )

    def latest(self) -> ObservationProjection | None:
        return self.cache.latest(self.project_id, self.device_id)

    def raw_observation(
        self, sample_id: str, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        current = now or datetime.now(UTC)
        key = (self.project_id, self.device_id, sample_id)
        cached = self._raw_cache.get(key)
        if cached is not None and current - cached[0] < RAW_CACHE_TTL:
            return cached[1]
        value = self.repository.get_full_observation(sample_id)
        safe_value = scrub_object(value)
        self._raw_cache[key] = (current, safe_value)
        return safe_value

    def clear_cache(self) -> None:
        self.cache.reset()
        self._raw_cache.clear()
