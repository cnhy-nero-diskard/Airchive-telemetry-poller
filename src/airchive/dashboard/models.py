"""Safe normalized values shared by Firestore, SQLite, and the UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from airchive.observation.state import principal_fields


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


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
class ObservationProjection:
    sample_id: str
    scheduled_at: datetime | None
    observed_at: datetime | None
    persisted_at: datetime | None
    reconciled_at: datetime | None
    local_date: str | None
    timezone: str | None
    completeness: int | None
    raw_daily_total: str | None
    raw_daily_total_number: float | None
    unit: str | None
    interval_value: str | None
    interval_value_number: float | None
    interval_seconds: float | None
    interval_status: str | None
    flags: tuple[str, ...]
    energy_ok: bool | None
    energy_failure_class: str | None
    state_ok: bool | None
    state_failure_class: str | None
    principal_state: dict[str, Any]
    metadata_version: str | None
    collector_version: str | None
    storage_path: str

    @classmethod
    def from_document(
        cls, document: dict[str, Any] | None, *, storage_path: str = ""
    ) -> ObservationProjection | None:
        if not isinstance(document, dict):
            return None
        sample_id = _text(document.get("sampleId"))
        if sample_id is None:
            return None

        energy = _mapping(document.get("energy"))
        quality = _mapping(document.get("quality"))
        source = _mapping(document.get("source"))
        energy_source = _mapping(source.get("energy"))
        state_source = _mapping(source.get("state"))
        flags_value = quality.get("flags")
        flags = (
            tuple(flag for flag in flags_value if isinstance(flag, str))
            if isinstance(flags_value, list | tuple)
            else ()
        )

        return cls(
            sample_id=sample_id,
            scheduled_at=_instant(document.get("scheduledAt")),
            observed_at=_instant(document.get("observedAt")),
            persisted_at=_instant(document.get("persistedAt")),
            reconciled_at=_instant(document.get("reconciledAt")),
            local_date=_text(document.get("localDate")),
            timezone=_text(document.get("timezone")),
            completeness=_integer(document.get("completeness")),
            raw_daily_total=_text(energy.get("rawDailyTotal")),
            raw_daily_total_number=_number(energy.get("rawDailyTotalNumber")),
            unit=_text(energy.get("unit")),
            interval_value=_text(energy.get("intervalValue")),
            interval_value_number=_number(energy.get("intervalValueNumber")),
            interval_seconds=_number(energy.get("intervalSeconds")),
            interval_status=_text(quality.get("intervalStatus")),
            flags=flags,
            energy_ok=_boolean(energy_source.get("ok")),
            energy_failure_class=_text(energy_source.get("failureClass")),
            state_ok=_boolean(state_source.get("ok")),
            state_failure_class=_text(state_source.get("failureClass")),
            principal_state=principal_fields(_mapping(document.get("state"))),
            metadata_version=_text(document.get("metadataVersion")),
            collector_version=_text(document.get("collectorVersion")),
            storage_path=storage_path,
        )

    def to_json_value(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("scheduled_at", "observed_at", "persisted_at", "reconciled_at"):
            instant = value[name]
            value[name] = instant.isoformat() if instant is not None else None
        value["flags"] = list(self.flags)
        return value

    @classmethod
    def from_json_value(cls, value: dict[str, Any]) -> ObservationProjection:
        restored = dict(value)
        for name in ("scheduled_at", "observed_at", "persisted_at", "reconciled_at"):
            restored[name] = _instant(restored.get(name))
        restored["flags"] = tuple(restored.get("flags") or ())
        restored["principal_state"] = _mapping(restored.get("principal_state"))
        return cls(**restored)

    def anomaly_document(self) -> dict[str, Any]:
        return {
            "quality": {"intervalStatus": self.interval_status, "flags": list(self.flags)}
        }
