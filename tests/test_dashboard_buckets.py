"""Aggregation of stored intervals into clock-aligned buckets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from airchive.dashboard.presentation import (
    bucket_options,
    bucket_rows,
    bucket_series,
)

MANILA = ZoneInfo("Asia/Manila")


def test_bucket_options_start_at_the_collector_cadence():
    assert list(bucket_options(300))[0] == "5 min samples"
    assert bucket_options(300)["1 hour"] == 3600
    # A coarser cadence never offers a width below itself, and never repeats it.
    labels = list(bucket_options(3600))
    assert labels[0] == "60 min samples"
    assert "30 minutes" not in labels
    assert labels.count("1 hour") == 0


def test_buckets_align_to_local_clock_boundaries(observations_factory):
    since = datetime(2026, 8, 23, 20, 40, tzinfo=UTC)  # 04:40 local
    until = datetime(2026, 8, 23, 23, 10, tzinfo=UTC)  # 07:10 local
    buckets = bucket_series(
        observations_factory(since, until, step_minutes=5),
        timezone=MANILA,
        bucket_seconds=3600,
        since=since,
        until=until,
        cadence_seconds=300,
    )

    assert [bucket.start.strftime("%H:%M") for bucket in buckets] == [
        "04:00",
        "05:00",
        "06:00",
        "07:00",
    ]
    assert all(bucket.expected_samples == 12 for bucket in buckets)


def test_missing_slots_stay_empty_instead_of_zero(observations_factory):
    since = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
    until = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
    observations = [
        item
        for item in observations_factory(since, until, step_minutes=5)
        if not (60 <= (item.observed_at - since).total_seconds() / 60 < 120)
    ]
    buckets = bucket_series(
        observations,
        timezone=MANILA,
        bucket_seconds=3600,
        since=since,
        until=until,
        cadence_seconds=300,
    )

    empty = [bucket for bucket in buckets if bucket.missing]
    assert len(empty) == 1
    assert empty[0].total is None
    assert empty[0].start.strftime("%H:%M") == "09:00"

    states = [row["state"] for row in bucket_rows(buckets)]
    assert states.count("No stored value") == 1
    assert "Complete" in states


def test_partial_coverage_is_reported_separately(observations_factory):
    since = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
    until = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    observations = observations_factory(since, until, step_minutes=5)[:4]
    buckets = bucket_series(
        observations,
        timezone=MANILA,
        bucket_seconds=3600,
        since=since,
        until=until,
        cadence_seconds=300,
    )

    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.partial
    assert bucket.usable_samples == 4
    assert bucket.expected_samples == 12
    assert bucket.total == sum(
        item.interval_value_number for item in observations
    )
    assert bucket_rows(buckets)[0]["state"] == "Partial coverage"


def test_bucket_totals_sum_only_stored_values(observations_factory):
    since = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
    until = since + timedelta(minutes=30)
    observations = observations_factory(since, until, step_minutes=5)
    observations[2] = observations[2].__class__(
        **{**observations[2].__dict__, "interval_value_number": None}
    )
    buckets = bucket_series(
        observations,
        timezone=MANILA,
        bucket_seconds=1800,
        since=since,
        until=until,
        cadence_seconds=300,
    )

    assert buckets[0].usable_samples == 5
    assert buckets[0].total == sum(
        item.interval_value_number
        for item in observations
        if item.interval_value_number is not None
    )
