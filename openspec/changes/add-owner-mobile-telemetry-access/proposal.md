## Why

Airchive's Firestore rules currently deny every mobile client because the collector and local dashboard use server credentials. The planned personal AirchiveApp needs direct, read-only access to this AC's history so it can maintain an on-device cache without introducing a continuously running read service.

## What Changes

- Permit one explicitly enrolled Firebase Authentication owner to read only the configured AC's device identity, telemetry, finalized daily totals, and collector health paths.
- Continue denying all mobile writes and all other document paths; keep the collector's server-side access and local dashboard behavior intact.
- Document the one-time owner enrollment, Firebase project setup, and the mobile read contract, including bounded initial history and incremental refresh after persistence or reconciliation updates.
- Add emulator-backed authorization and query tests before any rules deployment.
- If live review finds the required root device identity document missing, permit an explicitly authorized, create-only server-side bootstrap of that one document before enrollment; leave telemetry history and collector behavior unchanged.

## Capabilities

### New Capabilities

- `mobile-telemetry-access`: Owner-scoped Firestore reads and a documented contract for an Android-first client that caches Airchive history locally.

### Modified Capabilities

- `telemetry-persistence`: Replace the unconditional server-only client boundary with a deny-by-default rule and a narrowly scoped, read-only exception defined by `mobile-telemetry-access`; server-side collector credentials and all client-write denial remain unchanged.
- `local-telemetry-dashboard`: Preserve the dashboard's server-side, read-only Firestore access and explicitly keep its browser isolated from the separately authorized mobile client.

## Impact

- Changes Firestore security rules, rules tests, and operator setup documentation in this repository.
- Requires Firebase Authentication to be enabled for the same Firebase project and a deliberate owner UID enrollment before client reads work.
- Defines the data paths and timestamps consumed later by AirchiveApp. In-app onboarding, ThinQ token storage and direct control, and the Kotlin Multiplatform local database are implemented in the app repository, not by this change.
- Does not change collector writes, telemetry records, polling cadence, the local dashboard, or the private `POST /poll` service.
