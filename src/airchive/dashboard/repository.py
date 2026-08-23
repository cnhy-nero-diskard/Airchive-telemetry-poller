"""Read-only Firestore queries used by the dashboard."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from airchive.dashboard.models import ObservationProjection
from airchive.storage import paths

DEFAULT_PAGE_SIZE = 250

PROJECTION_FIELDS = (
    "sampleId",
    "scheduledAt",
    "observedAt",
    "persistedAt",
    "reconciledAt",
    "localDate",
    "timezone",
    "completeness",
    "energy.rawDailyTotal",
    "energy.rawDailyTotalNumber",
    "energy.unit",
    "energy.intervalValue",
    "energy.intervalValueNumber",
    "energy.intervalSeconds",
    "quality.intervalStatus",
    "quality.flags",
    "source.energy.ok",
    "source.energy.failureClass",
    "source.state.ok",
    "source.state.failureClass",
    "state.operation.airConOperationMode",
    "state.airConJobMode.currentJobMode",
    "state.temperature.currentTemperature",
    "state.temperature.targetTemperature",
    "state.temperature.unit",
    "state.airFlow.windStrength",
    "state.powerSave.powerSaveEnabled",
    "state.airClean.airCleanOperationMode",
    "metadataVersion",
    "collectorVersion",
)


class DashboardRepository:
    """A deliberately read-only subset of Firestore for one device."""

    def __init__(self, client: Any, device_id: str, *, page_size: int = DEFAULT_PAGE_SIZE):
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self._client = client
        self.device_id = device_id
        self.page_size = page_size

    @property
    def telemetry_ref(self):
        return self._client.collection(
            f"{paths.device_path(self.device_id)}/{paths.TELEMETRY}"
        )

    def _projected_pages(self, query: Any) -> Iterator[ObservationProjection]:
        page_query = query.select(PROJECTION_FIELDS).limit(self.page_size)
        while True:
            snapshots = list(page_query.stream())
            for snapshot in snapshots:
                projection = ObservationProjection.from_document(
                    snapshot.to_dict(), storage_path=snapshot.reference.path
                )
                if projection is not None:
                    yield projection
            if len(snapshots) < self.page_size:
                return
            page_query = query.select(PROJECTION_FIELDS).start_after(snapshots[-1]).limit(
                self.page_size
            )

    def observations_in_range(
        self, since: datetime, until: datetime
    ) -> list[ObservationProjection]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.telemetry_ref.where(filter=FieldFilter("observedAt", ">=", since))
            .where(filter=FieldFilter("observedAt", "<", until))
            .order_by("observedAt", direction="ASCENDING")
        )
        return list(self._projected_pages(query))

    def observations_changed_since(
        self, field_path: str, since: datetime
    ) -> list[ObservationProjection]:
        if field_path not in {"persistedAt", "reconciledAt"}:
            raise ValueError("unsupported dashboard mutation field")
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.telemetry_ref.where(
            filter=FieldFilter(field_path, ">=", since)
        ).order_by(field_path, direction="ASCENDING")
        return list(self._projected_pages(query))

    def get_health(self) -> dict[str, Any] | None:
        snapshot = self._client.document(paths.health_path(self.device_id)).get()
        return snapshot.to_dict() if snapshot.exists else None

    def get_reconciliation(self) -> dict[str, Any]:
        snapshot = self._client.document(paths.reconciliation_path(self.device_id)).get()
        return snapshot.to_dict() if snapshot.exists else {}

    def get_full_observation(self, sample_id: str) -> dict[str, Any] | None:
        snapshot = self._client.document(paths.telemetry_path(self.device_id, sample_id)).get()
        return snapshot.to_dict() if snapshot.exists else None
