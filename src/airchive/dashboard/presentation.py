"""Pure dashboard view models that preserve telemetry quality semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from airchive.dashboard.cache import SyncState
from airchive.dashboard.models import ObservationProjection
from airchive.storage.store import TelemetryStore


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


@dataclass(frozen=True)
class Overview:
    latest: ObservationProjection | None
    latest_age_seconds: float | None
    stale: bool
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    last_error_class: str | None
    last_error_message: str | None
    pending_reconciliations: int
    last_sync_at: datetime | None
    refresh_error_class: str | None


@dataclass(frozen=True)
class RangeSummary:
    total: float
    observed_slots: int
    expected_slots: int
    usable_slots: int
    anomaly_count: int
    complete: bool

    @property
    def coverage_label(self) -> str:
        return f"{self.usable_slots}/{self.expected_slots} usable intervals"


def build_overview(
    latest: ObservationProjection | None,
    sync_state: SyncState,
    *,
    now: datetime,
    cadence_seconds: int,
) -> Overview:
    health = sync_state.health or {}
    reconciliation = sync_state.reconciliation or {}
    pending = reconciliation.get("pending")
    pending_count = len(pending) if isinstance(pending, dict) else 0
    age = None
    if latest is not None and latest.observed_at is not None:
        age = max(0.0, (_instant(now) - latest.observed_at).total_seconds())
    raw_failures = health.get("consecutiveFailures")
    try:
        failures = max(0, int(raw_failures or 0))
    except (TypeError, ValueError):
        failures = 0
    return Overview(
        latest=latest,
        latest_age_seconds=age,
        stale=latest is None or age is None or age > cadence_seconds * 1.5,
        last_attempt_at=_instant(health.get("lastAttemptAt")),
        last_success_at=_instant(health.get("lastSuccessAt")),
        consecutive_failures=failures,
        last_error_class=(
            health.get("lastErrorClass")
            if isinstance(health.get("lastErrorClass"), str)
            else None
        ),
        last_error_message=(
            health.get("lastErrorMessage")
            if isinstance(health.get("lastErrorMessage"), str)
            else None
        ),
        pending_reconciliations=pending_count,
        last_sync_at=sync_state.last_success_at,
        refresh_error_class=sync_state.last_error_class,
    )


def is_anomalous(observation: ObservationProjection) -> bool:
    return TelemetryStore.is_anomalous(observation.anomaly_document())


def summarize_range(
    observations: list[ObservationProjection],
    *,
    since: datetime,
    until: datetime,
    cadence_seconds: int,
) -> RangeSummary:
    expected = max(0, math.ceil((until - since).total_seconds() / cadence_seconds))
    usable = [
        item.interval_value_number
        for item in observations
        if item.interval_value_number is not None
    ]
    anomaly_count = sum(1 for item in observations if is_anomalous(item))
    return RangeSummary(
        total=sum(usable),
        observed_slots=len(observations),
        expected_slots=expected,
        usable_slots=len(usable),
        anomaly_count=anomaly_count,
        complete=len(observations) >= expected and len(usable) >= expected,
    )


def chart_rows(
    observations: list[ObservationProjection], timezone: ZoneInfo
) -> list[dict[str, Any]]:
    rows = []
    for item in observations:
        if item.observed_at is None:
            continue
        rows.append(
            {
                "observedAt": item.observed_at.astimezone(timezone),
                "intervalValue": item.interval_value_number,
                "intervalStatus": item.interval_status or "UNAVAILABLE",
                "anomalous": is_anomalous(item),
            }
        )
    return rows


@dataclass(frozen=True)
class Bucket:
    """One aggregation slot over stored intervals, in the display timezone."""

    start: datetime
    end: datetime
    total: float | None
    usable_samples: int
    expected_samples: int
    anomaly_count: int

    @property
    def missing(self) -> bool:
        return self.usable_samples == 0

    @property
    def partial(self) -> bool:
        return 0 < self.usable_samples < self.expected_samples


def bucket_options(cadence_seconds: int) -> dict[str, int]:
    """Return selectable aggregation widths, from raw samples upward."""
    options = {f"{max(1, cadence_seconds // 60)} min samples": cadence_seconds}
    for label, seconds in (
        ("30 minutes", 1800),
        ("1 hour", 3600),
        ("3 hours", 10800),
        ("6 hours", 21600),
        ("1 day", 86400),
    ):
        if seconds > cadence_seconds:
            options[label] = seconds
    return options


def _day_anchor(moment: datetime, timezone: ZoneInfo) -> datetime:
    local = moment.astimezone(timezone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_series(
    observations: list[ObservationProjection],
    *,
    timezone: ZoneInfo,
    bucket_seconds: int,
    since: datetime,
    until: datetime,
    cadence_seconds: int,
) -> list[Bucket]:
    """Aggregate stored intervals into contiguous clock-aligned buckets.

    Buckets are anchored to local midnight so hourly and multi-hour slots line
    up with wall-clock boundaries. Empty buckets are returned as missing rather
    than dropped, and their total stays ``None`` instead of a measured zero.
    """
    width = timedelta(seconds=bucket_seconds)
    anchor = _day_anchor(since, timezone)
    expected = max(1, round(bucket_seconds / cadence_seconds))
    totals: dict[datetime, list[float]] = {}
    anomalies: dict[datetime, int] = {}

    for item in observations:
        if item.observed_at is None:
            continue
        local = item.observed_at.astimezone(timezone)
        elapsed = (local - anchor).total_seconds()
        start = anchor + timedelta(seconds=(elapsed // bucket_seconds) * bucket_seconds)
        if item.interval_value_number is not None:
            totals.setdefault(start, []).append(item.interval_value_number)
        if is_anomalous(item):
            anomalies[start] = anomalies.get(start, 0) + 1

    buckets: list[Bucket] = []
    start = anchor + timedelta(
        seconds=((since.astimezone(timezone) - anchor).total_seconds() // bucket_seconds)
        * bucket_seconds
    )
    local_until = until.astimezone(timezone)
    while start < local_until:
        values = totals.get(start, [])
        buckets.append(
            Bucket(
                start=start,
                end=start + width,
                total=sum(values) if values else None,
                usable_samples=len(values),
                expected_samples=expected,
                anomaly_count=anomalies.get(start, 0),
            )
        )
        start += width
    return buckets


def bucket_rows(buckets: list[Bucket]) -> list[dict[str, Any]]:
    """Render buckets as plotting rows with an explicit coverage state."""
    rows = []
    for bucket in buckets:
        if bucket.missing:
            state = "No stored value"
        elif bucket.partial or bucket.anomaly_count:
            state = "Partial coverage"
        else:
            state = "Complete"
        rows.append(
            {
                "start": bucket.start,
                "end": bucket.end,
                "total": bucket.total,
                "state": state,
                "usableSamples": bucket.usable_samples,
                "expectedSamples": bucket.expected_samples,
            }
        )
    return rows
