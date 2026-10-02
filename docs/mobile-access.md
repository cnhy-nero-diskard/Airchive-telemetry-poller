# Airchive mobile telemetry access

This is the backend handoff for the separate AirchiveApp project. The app uses
Firebase Authentication for identity and reads historical Firestore data; it
does not receive collector service credentials or gain any write/control access.

## Rollout status and safety gate

**Completed 2026-10-02:** Google sign-in, stable owner UID, deployed collector
identity, active-rules backup, authorized identity bootstrap, and reviewed
read-only enrollment are verified. Five live phone authorization tests passed,
and post-deployment collector writes and dashboard server reads remain healthy.
The repository rules template remains closed; production uses the separately
reviewed enrollment copy documented below.

This completes the backend access change, not the full mobile app. The installed
debug app still displays demo history/device data and uses memory-only demo
ThinQ credential storage. Do not enter a real ThinQ PAT into this build. Live
history/cache wiring, secure ThinQ storage/control integration, release signing,
and the existing Android theme lint errors remain separate app work.

The following setup sections preserve the chronological verification record.

**Verified 2026-10-01:** Firebase project `airchive-telemetry-poller` is active.
Its `(default)` database is Firestore Native in `asia-southeast1`. The local
`.env` names this same project. `firebase apps:list ANDROID` returned no Android
clients, and an unauthenticated REST `get` of the locally configured device
document returned HTTP 403 (`PERMISSION_DENIED`).

At that point, the deployed Cloud Run configuration and the complete active
Firestore rules source had not been independently inspected: `gcloud` was not
on PATH. The Android package name, selected Firebase Auth provider, and owner
UID were also not available yet. The 403 confirms that this
unauthenticated document request is denied; it is not evidence that every
possible authenticated request was tested.

At that verification point, the implementation was limited to local work.
`firestore.rules` keeps mobile access disabled and owner/device identifiers as
pending markers. Emulator tests substitute fixture values in memory only.
Do not replace those markers, enable the rule gate, or deploy rules until the
owner UID, live collector device ID, target project, and active rules have been
reviewed and deployment is explicitly authorized.

### Android registration and Google sign-in setup — 2026-10-02

The user authorized Android registration and Google sign-in configuration,
without owner enrollment or a telemetry rules deployment.

- Registered Android package `cloud.airchive.personal`, display name
  `AirchiveApp`, in project `airchive-telemetry-poller`.
- Firebase application ID: `1:397051202974:android:ae3a9a9b3c0c3951645a8f`.
- Added SHA-1 and SHA-256 fingerprints from AirchiveApp's Gradle debug signing
  report. This registration covers the local debug APK, not a future release
  signing certificate.
- Enabled Google sign-in with Firebase CLI 15.26.0 using
  `firebase deploy --only auth --project airchive-telemetry-poller` and a
  separate temporary configuration containing only `auth.providers.googleSignIn`.
  Used `AirchiveApp` as the OAuth display name and the logged-in project
  account as the support email. No anonymous or email/password provider was
  requested, and no Firestore deployment target was included.
- The Authentication provisioning command created `Default Web App` as its
  backing Firebase client. This is a Firebase registration, not a deployed
  website or Hosting service.
- Re-fetched the Android SDK configuration and confirmed an Android OAuth
  client matching `cloud.airchive.personal` and the registered SHA-1, plus a
  Web OAuth client (`client_type: 3`).
- Populated all three public client options (`firebase.apiKey`,
  `firebase.applicationId`, and `firebase.googleWebClientId`) in the sibling
  app's `config/airchive-mobile.properties`. No token, private key, or
  service-account credential was copied into the app.
- No real owner sign-in has been tested. A successfully built APK is not proof
  of successful Google sign-in on the owner's phone.
- No Firestore rules were deployed or enabled, and no owner was enrolled.

Next: install the rebuilt debug APK on the owner's Android phone and use
`Continue with Google`. The app displays the Firebase UID when history access
is pending. Report that UID or a screenshot of the pending-access message;
never send an ID/access token or password. Expect access to remain denied
until the deployed collector/rules review and separately authorized enrollment
are complete. This is a sign-in test build, not verification of the app's
complete live history/control integration or private release delivery.

Setup verification:

- Firebase Authentication-only deployment: CLI returned success.
- Firebase SDK configuration: Android package/certificate and Web OAuth
  client present after provisioning; all required public options populated.
- AirchiveApp `:androidApp:assembleDebug`: completed and produced
  `androidApp/build/outputs/apk/debug/androidApp-debug.apk`.
- AirchiveApp `:shared:testAndroidHostTest`: successful, reported up-to-date.
- AirchiveApp `:androidApp:testDebugUnitTest`: no source tests; this is not
  evidence of Android instrumentation or real-phone sign-in verification.
- AirchiveApp `:androidApp:lintDebug`: failed with 2 errors and 4 warnings.
  Both errors concern `android:windowLightNavigationBar` in existing
  `values/styles.xml` and `values-night/styles.xml`: the attribute requires API
  27 while the app's minimum is 26. Those resources were not changed in this
  setup step. The APK assembled, but the combined validation command failed
  on lint; this is not a clean full validation pass.
- Strict OpenSpec validation for both changes and `git diff --check` in both
  repositories: passed (Git emitted Windows line-ending notices).
- Real phone sign-in, owner UID stability, denied-before/allowed-after reads,
  release signing, and collector/dashboard live checks: not performed.

### On-device Google chooser fix — 2026-10-02

The first debug APK stayed on `Signing in` on the owner's Android 16 phone.
An app-thread snapshot showed the main event loop responsive and coroutine
workers idle. Credential Manager logs showed the passive Google-ID request
reaching its provider and launching a chooser, but no result returning to the
app. This localized the observed stall before the Firebase credential exchange;
it did not prove a Firestore authorization failure or establish the underlying
provider/platform defect.

In AirchiveApp, changed the button request from the passive `GetGoogleIdOption`
to Google's documented explicit-button `GetSignInWithGoogleOption`. Bounded
chooser waiting to two minutes, Firebase exchange to 30 seconds, and the
device-identity authorization check to 30 seconds. Replaced blocking Firebase
Task waits with cancellable coroutine waits so those deadlines can release
the UI. Authorization-check timeout preserves the signed-in session and
reports `TIMEOUT`; denied reads still report access pending. Diagnostic logs
contain fixed stage messages or exception class names, never credentials.

Verification:

- Shared Android host tests: 278 passed, 0 failures/errors/skips, including
  authorization timeout, external cancellation, and preserved pending states.
- Debug app and instrumentation APK builds: passed.
- Eight focused instrumentation tests on the physical phone: passed. They
  exercise the explicit-button request and local Task completion, failure,
  timeout, cancellation, and late callbacks; they do not contact Firebase.
- Installed the updated debug APK over the existing app without clearing data.
- Opened `Continue with Google` and verified the Google `Choose an account`
  screen is now visible. No account was selected by the assistant; completed
  login and stable owner UID verification still require the owner.
- Strict OpenSpec validation for both changes and app `git diff --check`:
  passed. The earlier theme lint failures were not fixed in this scoped change.
- Firebase configuration and Firestore rules were not changed during this fix.

### Pre-enrollment live review — 2026-10-02

The owner successfully completed Google sign-in on the phone. The same Firebase
UID remained visible after an app process restart, and history access was still
pending/denied before enrollment.

Found the installed Cloud SDK at
`%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`; it was not on
PATH. Read-only inspection of `airchive-poll-svc` in `asia-southeast1`, explicitly
targeting `airchive-telemetry-poller`, confirmed the deployed `LG_DEVICE_ID`
matches AirchiveApp's configured device. The service reports ready, revision
`airchive-poll-svc-00001-s5q`, collector image `0.2.0`, and the expected
`airchive-collector` server identity.

Retrieved active release `projects/airchive-telemetry-poller/releases/cloud.firestore`
and ruleset `76f84e1e-a648-41b2-ac9c-d5604a09e4ca`. Its source denies every direct
client read and write. The Rules API initially required an explicit quota
project; adding `x-goog-user-project: airchive-telemetry-poller` resolved that
request without changing IAM permissions or reading credential files.

Prepared the rollout files at
`%LOCALAPPDATA%\Temp\opencode\airchive-mobile-rollout\`:

- `previous.firestore.rules`: backup verified against the independently
  retrieved active rules, normalizing only Windows line endings. SHA-256:
  `0324E8AAA4E48BECAEB1C2D964B836C74B660A4CE81268D07082C5E09FAA4E05`.
- `deny-all.firestore.rules`: minimal closed rollback.
- `enrolled.firestore.rules`: reviewed owner/device values and enabled gate;
  verified to match the repository template's logic with only those three
  enrollment substitutions (comments and whitespace excluded).
- `firebase.enrolled.json`, `firebase.previous.json`, and
  `firebase.deny-all.json`: each selects only its corresponding rules file.
- `review.json`: public project/app/UID/device/release identifiers; no tokens
  or service credentials.

The repository's `firestore.rules` remains a closed, disabled-by-default
template. The reviewed enrollment copy is the production deployment artifact;
fixture substitutions are never deployed. Preserve the rollout directory when
cleaning temporary files. To restore the backed-up rules:

```powershell
firebase deploy --only firestore:rules --project airchive-telemetry-poller --config "$env:LOCALAPPDATA\Temp\opencode\airchive-mobile-rollout\firebase.previous.json"
```

Alternatively deploy `firebase.deny-all.json`, or deliberately deploy the
closed repository template. All three rollback options stop future mobile
reads without writing server-side telemetry or removing the phone's cache.

### Deployment paused: missing device identity document — 2026-10-02

Before deployment, a read-only server smoke check confirmed that the configured
`devices/{deviceId}` identity document does not exist. Its `telemetry`
subcollection contains observations, and `runtime/collector` exists with last
success `2026-10-02T04:00:03.818378Z` and zero consecutive failures. Firestore
can contain subcollections even when their parent document is absent.

AirchiveApp's authorization check requires the identity document and fails
closed when it is missing. Enabling the reviewed rules alone would not complete
onboarding. The planned no-data-migration rollout therefore has an unmet
prerequisite: a one-time server-side identity bootstrap or a separately planned
persistence fix must be explicitly authorized before continuing. No production
rules or documents were changed during this enrollment attempt.

Pre-deployment checks completed:

- Active source and backup comparison passed after preserving the original
  Unicode comment character and normalizing Windows line endings.
- Rendered enrollment logic matches the closed template with only the reviewed
  gate/UID/device substitutions.
- Firestore rules emulator suite: 7 passed. Port 8080 was occupied, so the same
  suite ran with a separate temporary emulator configuration on 19081; no
  existing service was stopped. Missing local JS dependencies were installed
  from the lockfile with `npm ci --ignore-scripts` (0 audit vulnerabilities).
- Python suite: 258 passed, 10 skipped; lint passed. The skipped checks are
  environment-limited/opt-in checks, not evidence of a live deployment.
- Guarded live Android authorization tests compiled successfully, but were not
  run against production because enrollment remains blocked.
- A dashboard smoke check deliberately stopped on the missing identity
  prerequisite. Dashboard post-deployment reads and all live allowed/denied
  client checks remain unverified.

### Approved identity bootstrap — 2026-10-02

The user selected the one-time identity bootstrap rather than a collector code
change. Created the missing root document through server-side IAM access with
an atomic `exists=false` precondition. Its only fields are the verified
`deviceId` and server `updatedAt` (`2026-10-02T04:12:10.350000Z`). No alias,
model, or device type was guessed. Existing sampled documents in `telemetry`,
`dailyTotals`, `metadata`, and `runtime` retained their original update times
across the bootstrap check. No historical record, collector code, polling
configuration, or ThinQ control was changed.

### Rules deployed; initial phone verification pause — 2026-10-02

Deployed only the reviewed Firestore rules. Independently retrieved the active
release after deployment and confirmed its source exactly matches the reviewed
enrollment artifact (line endings normalized):

- Ruleset: `928f85ca-d1fb-490f-a5ff-710e302e56b6`.
- Release updated: `2026-10-02T04:14:15.795939Z`.
- Collector: subsequent scheduled `POST /poll` returned HTTP 200 at
  `2026-10-02T04:15:02.523058Z`; collector last success advanced to
  `2026-10-02T04:15:02.551066Z`, with zero consecutive failures.
- Dashboard server refresh: succeeded after deployment, reading six recent
  observations and the updated collector health through the existing IAM path.

Installation of the guarded live-test helper on the phone was denied with
`INSTALL_FAILED_USER_RESTRICTED` (installation canceled). No attempt was made
to bypass that restriction. At this stage the production client checks were
still pending. The user subsequently allowed USB installation and the checks
completed as recorded below. The checked-in rules template remains closed,
and the deny-all backup/rollback configurations remain available.

### Live phone verification completed — 2026-10-02

Installed the temporary instrumentation helper after the user explicitly
allowed USB installation. Ran only
`cloud.airchive.personal.data.auth.LiveOwnerAccessVerificationTest` on the
owner's physical phone, with its explicit live opt-in and reviewed owner UID
and device ID runner arguments. Result: **5 passed in 2.279 seconds**.

1. Existing owner's identity read from the production server succeeded and
   resolved to the configured device.
2. Explicit server-backed telemetry and daily-total queries with limit 1
   succeeded, as did the corresponding app adapter reads. Empty daily-total
   results are allowed; this is an authorization check, not a completeness
   assertion about historical coverage.
3. Explicit server-backed collector health read and its app projection succeeded.
4. A separate unauthenticated Firebase app's identity read returned
   `PERMISSION_DENIED`. It never signed out or replaced the owner's session.
5. The owner's attempted update of the existing `deviceId` to its identical
   value returned `PERMISSION_DENIED`; a server re-read confirmed it unchanged.
   No scratch documents or historical telemetry were written by the test.

The tests reused the persisted Firebase account without signing in again,
exporting tokens, or placing server credentials on the phone. Other UID/device,
unlisted-path, all write-operation, and page-bound cases remain covered by the
seven emulator tests; no second real account was created for this rollout.

Removed `cloud.airchive.personal.test` afterward and restarted the normal app
without clearing its data. Settings still shows the same signed-in owner and
the explicit warning not to enter a real PAT into its in-memory demo store.
The Home screen remains simulated: successful backend authorization does not
mean its demo history/provider wiring has been replaced with live data.

All 15 backend change tasks, including the separately authorized bootstrap,
are complete. The change has not been archived, committed, or pushed.

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
4. Render a separate enrollment copy of `firestore.rules` with the verified
   owner/device values and enabled gate, leaving the repository template closed.
   Review that only those three substitutions change the authorization logic.
   Run the Firestore emulator rules suite first, then explicitly authorize the
   rules-only deployment of that reviewed copy.
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

These earlier checks did not authorize or verify a live rules deployment.
The Cloud SDK was subsequently found outside PATH and Android registration,
owner sign-in, and pre-enrollment live review were completed as recorded above.
