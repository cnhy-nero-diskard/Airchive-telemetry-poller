"""Persistent, disposable projection cache for the local dashboard."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from airchive.dashboard.models import ObservationProjection
from airchive.redaction import scrub_object

SCHEMA_VERSION = 1


class CacheVersionError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _instant_text(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _utc(parsed)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return _instant_text(value)
    raise TypeError(f"unsupported cache value {type(value).__name__}")


def _safe_health(value: dict[str, Any] | None) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    allowed = {
        "lastAttemptAt",
        "lastSuccessAt",
        "lastSampleId",
        "lastSamplePath",
        "lastErrorAt",
        "lastErrorClass",
        "lastErrorMessage",
        "consecutiveFailures",
        "collectorVersion",
    }
    return scrub_object({key: source.get(key) for key in allowed if key in source})


def _safe_reconciliation(value: dict[str, Any] | None) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    pending = source.get("pending") if isinstance(source.get("pending"), dict) else {}
    safe_pending = {}
    for sample_id, entry in pending.items():
        if not isinstance(sample_id, str) or not isinstance(entry, dict):
            continue
        safe_pending[sample_id] = {
            key: entry.get(key)
            for key in ("previousLocalDate", "enqueuedAt")
            if key in entry
        }
    return scrub_object({"pending": safe_pending})


@dataclass(frozen=True)
class SyncState:
    watermark: datetime | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error_class: str | None = None
    health: dict[str, Any] | None = None
    reconciliation: dict[str, Any] | None = None


class DashboardCache:
    """SQLite cache. Firestore is authoritative; this file is always disposable."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = self._connect()
        try:
            self._initialize()
        except Exception:
            self._connection.close()
            raise

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.close()
            raise
        return connection

    def _initialize(self) -> None:
        result = self._connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError("dashboard cache integrity check failed")
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    project_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, device_id, sample_id)
                );
                CREATE INDEX IF NOT EXISTS observations_range
                    ON observations(project_id, device_id, observed_at);
                CREATE TABLE IF NOT EXISTS covered_ranges (
                    project_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    since_utc TEXT NOT NULL,
                    until_utc TEXT NOT NULL,
                    PRIMARY KEY (project_id, device_id, since_utc, until_utc)
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    project_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    watermark TEXT,
                    last_success_at TEXT,
                    last_attempt_at TEXT,
                    last_error_class TEXT,
                    health_json TEXT NOT NULL DEFAULT '{}',
                    reconciliation_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (project_id, device_id)
                );
                """
            )
            row = self._connection.execute(
                "SELECT schema_version FROM cache_meta WHERE singleton = 1"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO cache_meta(singleton, schema_version) VALUES (1, ?)",
                    (SCHEMA_VERSION,),
                )
            elif int(row[0]) != SCHEMA_VERSION:
                raise CacheVersionError(
                    f"unsupported dashboard cache schema {row[0]} (expected {SCHEMA_VERSION})"
                )

    @classmethod
    def open_recovering(
        cls, path: str | Path, *, now: datetime | None = None
    ) -> tuple[DashboardCache, Path | None]:
        cache_path = Path(path)
        try:
            return cls(cache_path), None
        except (sqlite3.DatabaseError, CacheVersionError):
            if not cache_path.exists():
                raise
            stamp = _utc(now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
            backup = cache_path.with_name(
                f"{cache_path.stem}.corrupt-{stamp}{cache_path.suffix}"
            )
            counter = 1
            while backup.exists():
                backup = cache_path.with_name(
                    f"{cache_path.stem}.corrupt-{stamp}-{counter}{cache_path.suffix}"
                )
                counter += 1
            shutil.move(cache_path, backup)
            return cls(cache_path), backup

    def close(self) -> None:
        self._connection.close()

    def reset(self) -> None:
        self.close()
        self.path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
        self._connection = self._connect()
        self._initialize()

    @staticmethod
    def _observation_row(
        project_id: str, device_id: str, observation: ObservationProjection
    ) -> tuple[str, str, str, str, str]:
        observed_at = (
            _instant_text(observation.observed_at) if observation.observed_at else ""
        )
        payload = json.dumps(
            scrub_object(observation.to_json_value()),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return project_id, device_id, observation.sample_id, observed_at, payload

    def _upsert_many(
        self,
        observations: Iterable[ObservationProjection],
        project_id: str,
        device_id: str,
    ) -> None:
        rows = [self._observation_row(project_id, device_id, item) for item in observations]
        self._connection.executemany(
            """
            INSERT INTO observations(
                project_id, device_id, sample_id, observed_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, device_id, sample_id) DO UPDATE SET
                observed_at = excluded.observed_at,
                payload_json = excluded.payload_json
            """,
            rows,
        )

    def upsert_observations(
        self,
        project_id: str,
        device_id: str,
        observations: Iterable[ObservationProjection],
    ) -> None:
        with self._connection:
            self._upsert_many(observations, project_id, device_id)

    def store_range(
        self,
        project_id: str,
        device_id: str,
        since: datetime,
        until: datetime,
        observations: Iterable[ObservationProjection],
    ) -> None:
        if until <= since:
            raise ValueError("range end must be after range start")
        with self._connection:
            self._upsert_many(observations, project_id, device_id)
            self._connection.execute(
                """
                INSERT OR IGNORE INTO covered_ranges(
                    project_id, device_id, since_utc, until_utc
                ) VALUES (?, ?, ?, ?)
                """,
                (project_id, device_id, _instant_text(since), _instant_text(until)),
            )

    def missing_ranges(
        self, project_id: str, device_id: str, since: datetime, until: datetime
    ) -> list[tuple[datetime, datetime]]:
        if until <= since:
            return []
        rows = self._connection.execute(
            """
            SELECT since_utc, until_utc FROM covered_ranges
            WHERE project_id = ? AND device_id = ?
              AND until_utc > ? AND since_utc < ?
            ORDER BY since_utc
            """,
            (project_id, device_id, _instant_text(since), _instant_text(until)),
        ).fetchall()
        cursor = _utc(since)
        end = _utc(until)
        missing: list[tuple[datetime, datetime]] = []
        for row in rows:
            covered_since = _parse_instant(row["since_utc"])
            covered_until = _parse_instant(row["until_utc"])
            if covered_since is None or covered_until is None or covered_until <= cursor:
                continue
            if covered_since > cursor:
                missing.append((cursor, min(covered_since, end)))
            cursor = max(cursor, covered_until)
            if cursor >= end:
                break
        if cursor < end:
            missing.append((cursor, end))
        return [(start, stop) for start, stop in missing if stop > start]

    def observations(
        self,
        project_id: str,
        device_id: str,
        since: datetime,
        until: datetime,
        *,
        descending: bool = False,
    ) -> list[ObservationProjection]:
        direction = "DESC" if descending else "ASC"
        rows = self._connection.execute(
            f"""
            SELECT payload_json FROM observations
            WHERE project_id = ? AND device_id = ?
              AND observed_at >= ? AND observed_at < ?
            ORDER BY observed_at {direction}, sample_id {direction}
            """,  # noqa: S608 - direction is selected from a fixed boolean
            (project_id, device_id, _instant_text(since), _instant_text(until)),
        ).fetchall()
        return [ObservationProjection.from_json_value(json.loads(row[0])) for row in rows]

    def latest(self, project_id: str, device_id: str) -> ObservationProjection | None:
        row = self._connection.execute(
            """
            SELECT payload_json FROM observations
            WHERE project_id = ? AND device_id = ? AND observed_at != ''
            ORDER BY observed_at DESC, sample_id DESC LIMIT 1
            """,
            (project_id, device_id),
        ).fetchone()
        return ObservationProjection.from_json_value(json.loads(row[0])) if row else None

    def observation_count(self, project_id: str, device_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM observations WHERE project_id = ? AND device_id = ?",
            (project_id, device_id),
        ).fetchone()
        return int(row[0])

    def apply_incremental_sync(
        self,
        project_id: str,
        device_id: str,
        observations: Iterable[ObservationProjection],
        *,
        sync_started_at: datetime,
        health: dict[str, Any] | None,
        reconciliation: dict[str, Any] | None,
    ) -> None:
        safe_health = _safe_health(health)
        safe_reconciliation = _safe_reconciliation(reconciliation)
        with self._connection:
            self._upsert_many(observations, project_id, device_id)
            self._connection.execute(
                """
                INSERT INTO sync_state(
                    project_id, device_id, watermark, last_success_at, last_attempt_at,
                    last_error_class, health_json, reconciliation_json
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(project_id, device_id) DO UPDATE SET
                    watermark = excluded.watermark,
                    last_success_at = excluded.last_success_at,
                    last_attempt_at = excluded.last_attempt_at,
                    last_error_class = NULL,
                    health_json = excluded.health_json,
                    reconciliation_json = excluded.reconciliation_json
                """,
                (
                    project_id,
                    device_id,
                    _instant_text(sync_started_at),
                    _instant_text(sync_started_at),
                    _instant_text(sync_started_at),
                    json.dumps(safe_health, default=_json_default, sort_keys=True),
                    json.dumps(safe_reconciliation, default=_json_default, sort_keys=True),
                ),
            )

    def record_sync_failure(
        self,
        project_id: str,
        device_id: str,
        *,
        attempted_at: datetime,
        error_class: str,
    ) -> None:
        safe_class = error_class if error_class.isidentifier() else "RefreshError"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO sync_state(
                    project_id, device_id, last_attempt_at, last_error_class
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, device_id) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_error_class = excluded.last_error_class
                """,
                (project_id, device_id, _instant_text(attempted_at), safe_class),
            )

    def sync_state(self, project_id: str, device_id: str) -> SyncState:
        row = self._connection.execute(
            "SELECT * FROM sync_state WHERE project_id = ? AND device_id = ?",
            (project_id, device_id),
        ).fetchone()
        if row is None:
            return SyncState(health={}, reconciliation={})
        return SyncState(
            watermark=_parse_instant(row["watermark"]),
            last_success_at=_parse_instant(row["last_success_at"]),
            last_attempt_at=_parse_instant(row["last_attempt_at"]),
            last_error_class=row["last_error_class"],
            health=json.loads(row["health_json"] or "{}"),
            reconciliation=json.loads(row["reconciliation_json"] or "{}"),
        )
