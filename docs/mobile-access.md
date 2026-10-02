# Airchive mobile telemetry access

This is the backend handoff for the separate AirchiveApp project. The app uses
Firebase Authentication for identity and reads historical Firestore data; it
does not receive collector service credentials or gain any write/control access.

## Rollout status and safety gate

**Verified 2026-10-01:** Firebase project `airchive-telemetry-poller` is active.
Its `(default)` database is Firestore Native in `asia-southeast1`. The local
`.env` names this same project. `firebase apps:list ANDROID` returned no Android
clients, and an unauthenticated REST `get` of the locally configured device
document returned HTTP 403 (`PERMISSION_DENIED`).

The deployed Cloud Run configuration and the complete active Firestore rules
source have not been independently inspected: `gcloud` is unavailable in the
implementation environment. The Android package name, selected Firebase Auth
provider, and owner UID are also not available yet. The 403 confirms that this
unauthenticated document request is denied; it is not evidence that every
possible authenticated request was tested.

Accordingly, `firestore.rules` keeps mobile access disabled and owner/device
identifiers as pending markers. Emulator tests substitute fixture values in
memory only. Do not register an app, enable a provider, replace those markers,
enable the rule gate, or deploy rules until the package name, owner sign-in,
UID, live collector device ID, and project have been reviewed. No live Firebase
configuration has been changed for this implementation.

## Authentication and owner enrollment

When AirchiveApp is ready:

1. Register its exact Android application ID in Firebase project
   `airchive-telemetry-poller`. The current design selects Google sign-in;
   confirm that provider with the app implementation before enabling it.
2. Sign in with the intended owner account. Record the Firebase UID from the
   authenticated session; do not infer identity from an email address.
3. Independently verify the target project, active Firestore rules, and device
   ID configured on the deployed collector. Confirm that the device ID matches
   the intended single AC.
4. Update the pending owner/device values in `firestore.rules` and enable the
   enrollment gate only after reviewing the diff. Run the Firestore emulator
   rules suite first, then review and explicitly authorize any live deployment.
5. Verify that the enrolled owner can read an allowed document, another UID and
   an anonymous client cannot, and client writes remain denied. Confirm the
   server-side collector and local dashboard still work.

Until enrollment is deliberately enabled, sign-in alone must not grant access.
To revoke future server reads, disable the enrollment gate (or remove the owner
UID) and deploy the reviewed rules. This does not erase history already cached
on a phone; AirchiveApp owns local-cache removal on sign-out or account change.

Firebase Authentication is separate from the LG ThinQ Personal Access Token.
The Firebase session authorizes reads of stored history only. ThinQ credentials
are not Firebase credentials and must be handled by the app separately. Never
install a Google service-account key or collector credential on a phone.

## Allowed read contract

Every path is scoped to the one explicitly configured device ID:

| Path | Client access |
|---|---|
| `devices/{deviceId}` | Get the device identity document |
| `devices/{deviceId}/telemetry/{sampleId}` | Get one observation; list with an explicit limit from 1 through 250 |
| `devices/{deviceId}/dailyTotals/{localDate}` | Get one finalized daily total; list with an explicit limit from 1 through 250 |
| `devices/{deviceId}/runtime/collector` | Get collector health |

All other paths remain denied, including `metadata`,
`runtime/reconciliation`, any other device, and list access to the top-level
`devices` collection. All client creates, updates, and deletes remain denied,
including writes by the enrolled owner. The collector and local dashboard use
their existing server-side credentials; Firestore client rules do not replace
those identities.

An allowed document is returned whole. In particular, an observation includes
its `raw.energy` and `raw.state` provider payloads, and a daily total includes
its `raw` payload. These rules do not provide field-level redaction.

## History and synchronization

- Bootstrap a recent window (the initial suggestion is 24 hours) with bounded
  pages of at most 250 observations. Use `observedAt` for a requested time range.
- Use `dailyTotals/{localDate}` for finalized daily summaries over longer
  periods rather than repeatedly loading the full five-minute series.
- On a foreground refresh after the app's freshness threshold, or on an
  explicit refresh, query `persistedAt` and `reconciledAt` separately from an
  overlapped last-successful watermark. Page each query with a limit of at most
  250, merge by `sampleId`, and tolerate duplicates from the overlap.
- Advance the local watermark only after all pages from both queries and the
  local database transaction succeed. A failed or partial refresh must be
  retried from the prior watermark.
- `persistedAt` identifies new or upgraded observations. `reconciledAt`, when
  present, identifies an older observation patched during day-rollover
  reconciliation. It is optional and not every observation has it.
- Preserve the energy unit, source outcomes, completeness, interval status and
  quality flags. A null `energy.intervalValue` is missing/incomplete data, not
  zero consumption. Display anomalous quality as flagged rather than silently
  treating it as normal.
- Stored observations are sampled history, not live device state. Live ThinQ
  state is a separate app-side ThinQ API operation and is not provided by these
  Firestore rules.

## Local verification

The rules suite uses fixture identities and the Firestore emulator; it never
contacts the production project:

```bash
npm install
npm run test:rules
```

The committed rules file remains disabled by default. The test harness enables
the owner/device checks only in the emulator's in-memory rules text, so fixture
identities cannot grant access to the live Firebase project.

### Verification record

Verified locally on 2026-10-01:

- `npm run test:rules`: 7 passed against the Firestore emulator.
- Python suite: 249 passed; 9 Firestore-emulator tests were skipped because the
  general Python suite was run without the emulator host, and 1 live-verification
  test was skipped because it is opt-in.
- `ruff check src tests`: passed.
- `openspec validate add-owner-mobile-telemetry-access --strict`: passed.
- `git diff --check`: passed; Git emitted only its Windows line-ending notices.
- `npm audit`: 0 vulnerabilities.

These checks do not authorize or verify a live rules deployment. `gcloud` is not
available in this environment, and no Android app or owner UID is registered.
