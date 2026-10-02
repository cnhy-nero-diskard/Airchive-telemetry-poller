## Context

See `proposal.md` for motivation and `specs/mobile-telemetry-access/spec.md` for the access contract. The collector stores one AC under `devices/{deviceId}` with `telemetry`, `dailyTotals`, `metadata`, and `runtime` subcollections. Its Python collector and loopback dashboard use server credentials, so today's `firestore.rules` denies every client. The five-minute observations can later gain a better `persistedAt` version or a `reconciledAt` day-boundary patch. The app is a separate Kotlin Multiplatform repository and will keep its own database.

## Goals / Non-Goals

**Goals:**

- Make direct mobile reads possible for one owner and exactly one configured device without placing Google service credentials on the phone.
- Keep access fail-closed before enrollment and after revocation; bound collection queries.
- Give the future app enough documented data and sync semantics to avoid repeated full-history reads.

**Non-Goals:**

- Implementing AirchiveApp onboarding, its Room database, ThinQ token storage, or control commands here.
- Granting mobile write access, household accounts, device discovery across Firestore, or a public read API.
- Changing the poller, telemetry schema, local dashboard, or Cloud Run poll endpoint.

## Decisions

### D1: Use Firebase Authentication and an exact owner UID in rules

Register the Android app in the existing Firebase project and enable Google sign-in for the personal owner account. The first sign-in produces a UID while all client reads still fail. The operator checks that UID and the intended device ID, inserts both as exact values in reviewed rules, runs emulator tests, and deploys the rules. A different Firebase account or a merely signed-in account gains no read access. To revoke access, remove the UID from the rules and redeploy.

This one-owner bootstrap is deliberately manual. An allowlist document would add a rules lookup and billed read to authorization checks; custom claims would add an Admin SDK enrollment tool and token-refresh/revocation semantics. A public bearer URL would require a new service and repeat Backlogium's separate endpoint setup. These alternatives can be reconsidered for multi-user access later.

### D2: List only the four mobile-readable path shapes

Add explicit rules for the configured `devices/{deviceId}` document; its `telemetry/{sampleId}` and `dailyTotals/{localDate}` collections; and `runtime/collector`. Every read checks both UID and device ID. `get` is allowed for those paths; telemetry and daily-total `list` requests require a small explicit limit, initially at most 250 documents. No other `list` or write operation is allowed. Keep the recursive deny-all fallback.

The owner receives whole documents. Firestore security rules do not hide `raw.energy`, `raw.state`, or the daily-total raw response inside an allowed document. Bounded history and a local projection limit transfers; a later split into client-safe projection documents is a separate data-model change if needed.

### D3: Publish a concrete client read and onboarding handoff

Document the client path, required Firebase sign-in, separate LG ThinQ Personal Access Token, and no-service-account rule. The app's first-run flow can sign in, show an "access pending" state until UID enrollment, accept and verify the ThinQ token/country against the existing AC, then fill its local database. The app repository owns that UI, secure token storage, and direct ThinQ requests.

For history, bootstrap a bounded recent window (for example 24 hours, in pages of at most 250) and load finalized `dailyTotals` for longer daily views instead of repeatedly scanning months of five-minute observations. On foreground return after a freshness threshold or manual refresh, query both `persistedAt` and `reconciledAt` from an overlapped last-successful watermark, merge by `sampleId`, and advance the on-device watermark only after all pages and the local transaction succeed. An explicit user-selected historical interval can be fetched once and cached. Avoid a perpetual Firestore listener or background polling. Show cache age and distinguish sampled state from live ThinQ status; null energy intervals stay gaps.

Existing single-field indexes support the timestamp and date queries; `raw` remains exempt from indexing. Confirm the exact Android SDK queries against the emulator and add an index only if an actual chosen query requires it.

### D4: Verify authorization before any live deployment

Automate rules tests in the Firebase emulator for enrolled owner, other UID, anonymous client, other device, unlisted paths, all client writes, bounded and unbounded collection queries. Exercise representative `persistedAt`, `reconciledAt`, and daily-total queries against seeded documents. After deployment, perform a signed-in client read and an unauthorized read, then verify the collector's server-side poll path and local dashboard still work. Do not use live reads as the only authorization test.

### D5: Keep production access closed until the app identity exists

The local-only implementation is authorized to build and test the rules with emulator fixture identities, but not to enroll a real owner or change live Firebase configuration. On 2026-10-01, Firebase CLI confirmed project `airchive-telemetry-poller` and its `(default)` Firestore database in `asia-southeast1`; `firebase apps:list ANDROID` returned no Android clients, and an unauthenticated document read returned HTTP 403. The local `.env` names the same project and contains a configured device ID, but `gcloud` is unavailable, so the deployed Cloud Run device ID and full live rules configuration could not be independently compared. Keep the checked-in rules behind an explicit disabled-by-default enrollment gate with unset owner/device placeholders. Emulator tests may substitute fixture values and enable that gate only in the emulator rules text. Do not register an app, enable an Auth provider, insert a real owner UID, or deploy rules until the app package, provider, signed-in owner UID, deployed device ID, and target project have been reviewed.

## Risks / Trade-offs

- [A wrong UID or device ID blocks onboarding or grants the wrong account access] -> Keep rules deny-all until the operator verifies both exact identifiers; test them in the emulator and smoke-test after deployment.
- [An authorized phone can read full raw documents] -> Limit access to one owner, keep credentials out of stored payloads, and bound collection pages; document the full-document exposure.
- [An offline phone retains cached history after server revocation] -> State that rules stop future server reads, while cache removal is an AirchiveApp responsibility on sign-out or account change.
- [A resumed app misses an upgraded or reconciled older sample] -> Query both mutation timestamps with overlap and commit the local watermark only after complete sync, following the existing dashboard pattern.
- [Existing collector spec says all client access is denied] -> At apply/archive time, reconcile the older `telemetry-persistence` statement with this explicitly authorized mobile exception rather than leaving contradictory canonical specs.

## Migration Plan

1. Keep existing deny-all rules until the future app can sign in and the owner UID is known. Register the Android app and enable the chosen Firebase Authentication provider in the same project.
2. Implement and test exact-path, UID, device, and query-limit rules locally. Document owner enrollment and revocation. No data migration is needed.
3. Review the intended Firebase project and owner/device identifiers before deploying rules. Perform authorized and denied mobile reads, then confirm collector and local-dashboard access.
4. Hand the documented read contract to AirchiveApp for first-run onboarding, local Room synchronization, and direct ThinQ controls.

Rollback: redeploy the previous deny-all rules. This stops new mobile server reads without modifying stored observations or collector access. Cached data already on a phone is cleared through the app's local account/cache controls.
