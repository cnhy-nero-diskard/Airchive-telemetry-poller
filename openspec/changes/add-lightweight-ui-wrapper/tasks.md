## 1. Dashboard foundation

- [x] 1.1 Add Streamlit to the application dependencies and create the packaged dashboard module structure; verify an editable install imports both `airchive` and the dashboard entry module successfully
- [x] 1.2 Add `airchive dashboard` CLI wiring that launches Streamlit in a child Python process bound to `127.0.0.1`; verify CLI tests assert the loopback binding and do not launch a real server
- [x] 1.3 Reuse dotenv and inspection-only configuration for the dashboard, including a user-local cache path and test override; verify tests accept Firestore/device/timezone settings without requiring any ThinQ credential and safely report missing configuration

## 2. Read-only Firestore access

- [x] 2.1 Define the normalized dashboard observation projection and conversion boundary, excluding `raw` and unused nested fields; verify mapper tests cover complete, partial, null, and malformed optional values
- [x] 2.2 Implement paginated projected range reads over `[since, until)` without the existing 500-document truncation; verify counting-fake tests cross a page boundary, preserve chronological order, and request no raw fields
- [x] 2.3 Implement incremental projected reads ordered by `persistedAt` and `reconciledAt`; verify tests surface a new sample, a completeness upgrade, and a reconciled older sample
- [x] 2.4 Implement health, reconciliation, and explicit full-document reads by sample ID; verify the full document is read only through the explicit detail method
- [x] 2.5 Keep the dashboard repository free of write and ThinQ-control operations; verify a read-only fake records zero writes across range, refresh, status, filter, and detail workflows

## 3. Persistent local cache

- [x] 3.1 Implement the versioned SQLite schema for project/device-scoped observations, covered ranges, synchronization state, health, and reconciliation status; verify isolated temporary databases initialize idempotently and keep projects/devices separate
- [x] 3.2 Implement atomic observation upserts and cached range queries; verify retries replace older projections by sample ID while reverse-chronological and chronological reads return the expected order
- [x] 3.3 Implement missing-range detection and transactional coverage markers; verify a failed paginated fetch stores no completed marker and a successful retry fetches only the uncovered span
- [x] 3.4 Implement incremental synchronization using overlapped `persistedAt` and `reconciledAt` watermarks captured at sync start; verify duplicate overlap is harmless and the watermark advances only after both queries and cache writes succeed
- [x] 3.5 Persist the last successful health/reconciliation snapshot and refresh metadata; verify a simulated Firestore outage retains prior cached data and records a failed refresh without advancing freshness
- [x] 3.6 Implement version/integrity checks, timestamped local recovery, and confirmation-gated cache reset; verify corruption and reset tests rebuild only local files and invoke no Firestore deletion
- [x] 3.7 Verify cache contents never persist raw payloads, credentials, authorization headers, registered sentinel secrets, or arbitrary exception representations

## 4. Dashboard data model and refresh flow

- [x] 4.1 Build timezone-aware overview models for collector health, staleness, latest energy, source outcomes, pending reconciliation, and principal device state; verify missing fields render as unavailable and cadence breaches render as stale
- [x] 4.2 Build range-series and anomaly models using the existing quality definitions; verify null intervals remain gaps, anomaly membership matches `TelemetryStore.is_anomalous`, and rendered timestamps use `LG_DAY_TIMEZONE`
- [x] 4.3 Implement consumption totals with observed/expected coverage metadata; verify only non-null stored intervals are summed and incomplete ranges always carry a visible warning state
- [x] 4.4 Implement startup, cadence-aligned automatic, and manual refresh orchestration; verify UI-only reruns read SQLite/session state while due or manual refreshes perform one incremental synchronization
- [x] 4.5 Implement explicit raw-detail loading with session or short-lived process caching keyed by project, device, and sample ID; verify ordinary overview/table rendering performs no full-document read and raw data never enters SQLite

## 5. Streamlit interface

- [x] 5.1 Build the page shell with last-sync status, refresh control, configured timezone, collector health, latest energy, and principal state cards; verify Streamlit app tests cover healthy, stale, failing, partial, and empty states
- [x] 5.2 Add bounded time-range controls, interval-consumption visualization, coverage summary, and visible gap/non-normal indicators; verify app tests do not plot null intervals as zero
- [x] 5.3 Add the reverse-chronological observation table, all/anomaly filtering, selected normalized details, and explicit raw-load action; verify app tests match CLI anomaly semantics and raw loading occurs only after the action
- [x] 5.4 Add cached-data warnings, actionable refresh failures, and confirmation-gated cache recovery/reset controls; verify app tests continue rendering cached observations during a simulated Firestore outage
- [x] 5.5 Inspect browser-visible output with sentinel credentials and verify it contains no token, authorization header, ambient credential content, or credential-file path

## 6. Documentation and verification

- [x] 6.1 Document local dashboard startup, loopback-only scope, environment requirements, default ranges, refresh cadence, cache location, stale-data behavior, raw-detail behavior, and safe reset/recovery; verify a clean local setup can follow the instructions without ThinQ credentials
- [x] 6.2 Run the dashboard repository and cache integration tests against the Firestore emulator; verify pagination, incremental upgrade/reconciliation refresh, raw-on-demand access, and zero writes
- [x] 6.3 Run the dashboard locally against ambient Firestore credentials and verify overview, chart, filters, detail, manual refresh, and cache reuse against stored telemetry without changing any Firestore document
- [x] 6.4 Run the full pytest suite and Ruff checks, verify existing collector/inspection behavior remains unchanged, run `openspec validate add-lightweight-ui-wrapper --strict`, and run `git diff --check`

## 7. Usability refinement

- [x] 7.1 Rework the dashboard into a plain-language hierarchy with a clear starting point, compact primary controls, friendly table labels, and progressive disclosure for collector, device, normalized, raw, and cache details; verify existing interaction and safety tests remain green
- [x] 7.2 Add a visible, non-color-only legend plus contextual hints for status, coverage, time range, refresh, anomaly filtering, and raw loading; verify Streamlit app tests assert the guidance remains browser-visible
