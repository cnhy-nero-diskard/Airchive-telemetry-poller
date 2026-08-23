## Context

Airchive is a Python 3.12 application whose collector and inspection commands use the server-side Firestore client with ambient credentials. Firestore client rules deny every direct browser read. Telemetry is stored every five minutes under a single device, ordered by mirrored `sampleId`; observations are mostly immutable but can be replaced by a more complete retry or patched during day-rollover reconciliation. Raw payloads dominate document size and are intentionally excluded from indexing. See `proposal.md` for motivation and `specs/local-telemetry-dashboard/spec.md` for observable behavior.

The existing CLI already exposes health, recent observations, anomalies, and individual observation reads through `TelemetryStore`. Its range reader is bounded to 500 results and returns complete documents, so the dashboard needs paginated projection reads rather than repeatedly calling that method for every rerun.

## Goals / Non-Goals

**Goals:**

- Keep the UI local, single-user, read-only, and straightforward to launch.
- Preserve the existing Firestore trust boundary and reuse inspection-only configuration.
- Make common health, energy, quality, and state questions answerable at a glance.
- Bound network and Firestore reads through projection queries and a recoverable persistent cache.
- Keep synchronization correct when retries upgrade observations or reconciliation patches older samples.

**Non-Goals:**

- Hosting, remote access, authentication, multi-user sessions, or mobile packaging.
- Device control, live ThinQ reads, collector configuration changes, or Firestore writes.
- Replacing Firestore as the source of truth or changing the telemetry schema.
- Long-term analytics, forecasting, billing estimates, or background aggregation jobs.
- Persistently duplicating raw source payloads in the dashboard cache.

## Decisions

### D1: Use Streamlit as a local UI process

Add an `airchive dashboard` CLI action that launches the packaged Streamlit app in a child Python process, binds it to `127.0.0.1`, and opens a local browser. The app loads the same `.env` and inspection configuration as `latest`, `health`, and `anomalies`; it does not load ThinQ credentials.

Streamlit fits the single-user local scope, supplies charts, tables, status components, and periodic reruns without a JavaScript build toolchain, and keeps implementation in the existing language. FastAPI plus HTMX would provide finer HTTP control but adds templates and client behavior with little benefit locally. A direct Firebase web client is rejected because it would require opening the deny-all rules and distributing an additional browser authentication model.

### D2: Keep all data access behind a dashboard read repository

Create a dashboard read repository over the existing Firestore client, device paths, anomaly predicate, and document conversion conventions. It will provide:

- paginated, field-projected observations over `[since, until)`;
- observations whose `persistedAt` changed since a watermark;
- observations whose `reconciledAt` changed since a watermark;
- health and reconciliation reads; and
- a direct full-document read by sample ID for explicit raw inspection.

The repository exposes no write method. Projection queries omit `raw`, metadata profiles, and unused nested state. Inequality filters order on the same field, allowing existing automatic single-field indexes to serve them without a new composite index. Pagination prevents the existing 500-document helper limit from truncating longer selected ranges.

Extending the write-oriented store directly was considered, but a separate read repository makes the no-write boundary testable and avoids changing collector behavior. It may reuse `TelemetryStore` helpers and references where doing so does not expose writes to the UI layer.

### D3: Persist a normalized projection in a user-local SQLite cache

Use Python's standard `sqlite3` module and place the cache beneath an Airchive-specific directory in the current user's profile. Allow a dedicated environment override for tests and operators who need a different cache location. Key every record by `(project_id, device_id, sample_id)` so different projects or devices cannot collide.

The cache stores timestamps, energy values and units, quality status and flags, source outcomes, selected principal state, completeness, metadata/collector versions, and storage identity. It does not persist raw payloads, credentials, authorization material, or arbitrary exception objects. Firestore timestamp values are normalized to UTC text for SQLite and converted back to timezone-aware values at the boundary.

SQLite is chosen over Streamlit's in-memory/data cache because it survives page reruns and process restarts, and over a JSON file because range queries, atomic upserts, schema versioning, and corruption recovery are simpler. Firestore remains authoritative; deleting the cache is always safe.

### D4: Track range coverage separately from synchronization freshness

The cache maintains two kinds of state per project/device:

1. **Covered time spans** record which historical observation ranges completed successfully. Missing spans are fetched in bounded pages, written in one SQLite transaction, and marked covered only after the final page succeeds.
2. **A successful synchronization watermark** records the start time of the last fully successful incremental refresh.

Before refreshing, capture `sync_started_at`. Query both `persistedAt` and `reconciledAt` from the previous watermark with a small overlap, merge results by sample ID, and atomically upsert them. Advance the watermark to `sync_started_at` only after both queries and the SQLite transaction succeed. The overlap makes duplicate reads possible but prevents edge-boundary loss; upserts make duplicates harmless.

`persistedAt` discovers new samples and completeness upgrades because an upgraded document is replaced with a new persistence time. `reconciledAt` independently discovers patches to older rollover samples. Querying only `sampleId > latest_cached` was rejected because it would miss both forms of mutation. Refetching the entire visible window on every Streamlit rerun was rejected because read volume grows with window size rather than with change volume.

### D5: Separate slow-changing telemetry from small mutable status records

Telemetry synchronization runs automatically no faster than the five-minute collector cadence and on explicit manual refresh. Health and reconciliation are small mutable documents; read them during each synchronization and cache their last successful values with the sync metadata. UI-only reruns caused by filters, table selection, or expanders read SQLite and session state rather than Firestore.

The page always shows the last successful synchronization time. If refresh fails, cached telemetry remains visible with a stale/error banner, and the watermark is not advanced. If no cache exists, the same failure is shown as an empty-state connection error.

### D6: Fetch full raw documents only through explicit detail action

The observation table and charts use the SQLite projection. Selecting a row shows normalized cached details; expanding a separate raw-data section triggers one direct document read. The resulting full document remains only in the Streamlit session or a short-lived process cache keyed by project, device, and sample ID. It is never inserted into SQLite.

This retains the ability to inspect provider payloads without transferring 2–4 KB of raw data for every chart point. Prefetching raw documents was rejected because it negates Firestore field projection and the primary cache benefit.

### D7: Preserve interval meaning in every aggregate and chart

Charts use `energy.intervalValueNumber` and leave null values as gaps. Non-normal statuses and independent flags remain visible in an adjacent status layer/table. A selected-range total sums only non-null stored intervals and is paired with observed/expected slot coverage plus a warning when any interval is missing or unusable. Times are rendered in `LG_DAY_TIMEZONE`, while cache synchronization remains UTC.

The initial page contains:

```text
+--------------------------------------------------------------+
| Airchive  [last sync] [Refresh] [Clear cache]                |
+----------------+----------------+-----------------------------+
| Collector      | Latest energy  | Latest device state         |
| health / age   | raw + interval | operation / mode / temp     |
+----------------+----------------+-----------------------------+
| Range + timezone | interval-consumption chart + coverage     |
+--------------------------------------------------------------+
| Recent observations [all | anomalies]                       |
| selected normalized details [Load raw payload]              |
+--------------------------------------------------------------+
```

### D8: Version and recover the cache locally

Store a cache schema version and migrate only simple compatible revisions. If integrity checks or schema initialization fail, close the connection, move the invalid database to a timestamped local backup, and create a fresh cache after explicit notice. The UI also exposes a confirmation-gated cache reset. Neither path calls Firestore deletion APIs.

## Risks / Trade-offs

- **[Streamlit reruns accidentally cause duplicate reads]** -> Isolate Firestore access in synchronization and explicit raw-load functions; render all other interactions from SQLite/session state and test rerun behavior with a counting fake.
- **[An observation changes near a refresh boundary]** -> Use both mutation timestamps, an overlap window, atomic upserts, and advance the watermark only after a complete successful refresh.
- **[Cache contents become stale while the app is closed]** -> Run incremental synchronization at startup before presenting data as current and always display the last successful sync age.
- **[The local cache contains sensitive household telemetry]** -> Store only the normalized display projection in the current user's profile, document the location, and provide a cache-clear action; never store credentials or raw payloads.
- **[Long ranges produce many initial reads]** -> Default to 24 hours, fetch only uncovered spans with field projection and pagination, and make larger ranges explicit user choices.
- **[Firestore projection lowers bandwidth but not document-read accounting]** -> The persistent range cache and incremental mutation queries provide the request/read reduction; projection is an additional latency and transfer optimization only.
- **[A local process is accidentally exposed on the network]** -> Force loopback binding in the supported CLI launch path and document that remote hosting is outside the security model.

## Migration Plan

1. Add the dashboard dependency, package modules, read repository, and versioned cache behind the new CLI action; collector commands remain unchanged.
2. Validate cache/query behavior with fake Firestore and temporary SQLite databases, then run existing collector and inspection tests to prove no write-path regression.
3. Run the dashboard locally against the Firestore emulator and then ambient credentials, verifying browser-visible data contains no secrets and Firestore records remain unchanged.
4. Document startup, ranges, refresh cadence, cache location, stale-data behavior, and reset/recovery.

Rollback is removal of the dashboard command and dependency. Existing local cache files may be deleted independently; Firestore and collected telemetry require no migration or rollback.

## Open Questions

- The exact set of principal state fields shown on the first page can follow the fields actually populated by this AC model without changing the data-access or cache design.
- Final visual colors and chart component selection can be tuned during implementation as long as status, gap, and accessibility requirements remain satisfied.
