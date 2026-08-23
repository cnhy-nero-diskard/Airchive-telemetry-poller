## Why

Airchive's terminal inspection commands expose the stored telemetry accurately, but they make it cumbersome to understand recent energy use, collector health, and anomalous intervals at a glance. A local-only visual wrapper can make the existing Firestore data easier to inspect while preserving deny-all client rules and avoiding repeated reads of unchanged history.

## What Changes

- Add a local Streamlit dashboard launched through the Airchive CLI and bound to the loopback interface by default.
- Present collector health, latest stored state, recent energy intervals, quality gaps, anomalies, and observation details without adding control actions or Firestore writes.
- Add time-range charts and tables that preserve Airchive's interval-quality semantics rather than treating missing or unresolved consumption as zero.
- Add a user-local SQLite projection cache that performs incremental refreshes, revalidates upgraded or reconciled observations, and fetches bulky raw payloads only on demand.
- Reuse the existing inspection configuration and server-side Firestore credentials; keep direct browser access denied.
- Document local startup, cache behavior, refresh behavior, and cache reset/recovery.

## Capabilities

### New Capabilities

- `local-telemetry-dashboard`: A read-only, local Streamlit interface for health, telemetry, charts, anomalies, observation details, and cache-efficient Firestore synchronization.

### Modified Capabilities

None.

## Impact

- Adds Streamlit as an application dependency and uses Python's standard SQLite support for the local cache.
- Adds dashboard modules, CLI wiring, query/cache adapters, tests, and operator documentation.
- Reuses the existing `TelemetryStore`, `FIREBASE_PROJECT_ID`, `LG_DEVICE_ID`, timezone configuration, and ambient Google credentials.
- Does not change the collector schedule, telemetry schema, Firestore security rules, ThinQ access, or deployed Cloud Run Job.
