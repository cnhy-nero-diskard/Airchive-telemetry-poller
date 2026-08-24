"""Shared observation builders for dashboard tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airchive.dashboard.models import ObservationProjection


def projection(
    observed_at: datetime,
    *,
    value: float | None = 1.0,
    status: str = "NORMAL",
    flags: list[str] | None = None,
    daily_total: float = 0.0,
) -> ObservationProjection:
    item = ObservationProjection.from_document(
        {
            "sampleId": observed_at.strftime("%Y%m%dT%H%M%SZ"),
            "scheduledAt": observed_at,
            "observedAt": observed_at,
            "persistedAt": observed_at,
            "localDate": observed_at.date().isoformat(),
            "timezone": "Asia/Manila",
            "completeness": 3,
            "energy": {
                "rawDailyTotalNumber": daily_total,
                "unit": "Wh",
                "intervalValueNumber": value,
                "intervalSeconds": 300,
            },
            "quality": {"intervalStatus": status, "flags": flags or []},
            "source": {"energy": {"ok": True}, "state": {"ok": True}},
            "state": {},
        },
        storage_path=f"devices/device-1/telemetry/{observed_at.isoformat()}",
    )
    assert item is not None
    return item


def series(
    since: datetime,
    until: datetime,
    *,
    step_minutes: int = 5,
    value: float = 1.0,
) -> list[ObservationProjection]:
    moment = since.astimezone(UTC)
    items = []
    index = 0
    while moment < until:
        index += 1
        items.append(projection(moment, value=value, daily_total=float(index)))
        moment += timedelta(minutes=step_minutes)
    return items
