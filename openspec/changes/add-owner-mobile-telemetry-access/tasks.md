## 1. Confirm current project facts and preserve the rollout gate

- [x] 1.1 Record the read-only Firebase verification in `docs/mobile-access.md`: project `airchive-telemetry-poller`, `(default)` database in `asia-southeast1`, no registered Android app, and an unauthenticated document read denied with HTTP 403. State that the local `.env` project matches but the deployed Cloud Run device ID and full rules source remain unverified because `gcloud` is unavailable; do not include tokens or service credentials.
- [ ] 1.2 When the AirchiveApp Android package and owner sign-in are ready, register that Android client and enable Google sign-in in the same project; verify a stable Firebase UID while client reads remain denied before enrollment. **Deferred by user decision: local-only implementation first.**
- [ ] 1.3 Before enrolling an owner, verify the deployed Cloud Run device ID and current deployed rules against the intended project and the operator-confirmed device ID. **Deferred until Cloud Run inspection access is available.**

## 2. Implement narrow Firestore access

- [x] 2.1 Add exact owner UID and device ID checks to the four allowed Firestore path shapes behind an explicitly disabled source-rule gate and pending markers; in emulator-only rules text, substitute fixture values and verify reads succeed only for the fixture owner and device while the checked-in rules remain closed.
- [x] 2.2 Require an explicit page limit of at most 250 for telemetry and daily-total list queries; verify bounded queries succeed and unbounded or oversized queries fail in the emulator.
- [x] 2.3 Add a repeatable Firestore rules test harness with seeded identity, telemetry, daily-total, health, metadata, and reconciliation documents; verify tests cover anonymous access, another UID, another device, every unlisted path, and create/update/delete denial, and confirm fixture substitutions never modify the checked-in rules or target a live project.
- [x] 2.4 Test bounded `observedAt`, `persistedAt`, `reconciledAt`, and daily-total queries against the emulator; verify the app's intended query shapes work and add an index only if a tested query requires one.

## 3. Document the app handoff

- [x] 3.1 Document first-run owner enrollment, Firebase sign-in versus the separate ThinQ token, the access-pending state, and revocation; verify a fresh operator can follow the steps without installing a service-account key on a phone.
- [x] 3.2 Document the allowed paths, full-document raw payload exposure, 250-document page bound, recent-history bootstrap, daily-total use, and dual-timestamp incremental sync contract; verify the handoff describes null intervals, units, quality flags, and separate live ThinQ state.
- [x] 3.3 Review the OpenSpec status of `telemetry-persistence` and `local-telemetry-dashboard`; add `MODIFIED` deltas that supersede global client-denial wording while preserving the dashboard's browser boundary, without changing historical artifacts. Verify strict validation and ensure the eventual synced requirements match the disabled-by-default deployed access boundary.

## 4. Validate and prepare rollout

- [x] 4.1 Run the Firestore emulator rules suite, existing Python tests and lint, `openspec validate add-owner-mobile-telemetry-access --strict`, and `git diff --check`; record the actual results and any environment-limited checks in `docs/mobile-access.md`.
- [ ] 4.2 Before any future live deployment, review the target project and owner/device values against the signed-in app and deployed collector; prepare a rules backup and deny-all rollback. **Deferred: the app identity and deployed collector values are not available.**
- [ ] 4.3 Once AirchiveApp sign-in is available and live deployment is authorized, deploy the reviewed rules; verify an owner client read succeeds, an unauthorized read and owner write fail, and collector plus local-dashboard server reads remain healthy.
- [x] 4.4 Exercise the deny-all source rules in the emulator and document how to revoke the owner in production; verify the closed rules deny mobile reads without changing server-side data.
