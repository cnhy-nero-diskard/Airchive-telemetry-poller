# Airchive — operations

Everything needed to run, understand, and inspect the collector. If you are
setting it up for the first time, start with [setup.md](setup.md) and come back
here.

- [What this is](#what-this-is)
- [Configuration](#configuration)
- [Running it](#running-it)
- [Deployment](#deployment)
- [The stored data model](#the-stored-data-model)
- [Interval and delta semantics](#interval-and-delta-semantics)
- [Day rollover and reconciliation](#day-rollover-and-reconciliation)
- [The quality model](#the-quality-model)
- [Idempotency](#idempotency)
- [Inspection commands](#inspection-commands)
- [Local dashboard](#local-dashboard)
- [Collector health](#collector-health)
- [Rate limiting](#rate-limiting)
- [Credential hygiene](#credential-hygiene)
- [Known device and API limitations](#known-device-and-api-limitations)
- [Storage growth](#storage-growth)
- [Future enhancements](#future-enhancements)
- [Testing](#testing)

---

## What this is

A headless collector for one LG air conditioner. Every five minutes it reads two
things through LG's official ThinQ Connect API — the device's cumulative
current-day energy counter and its full readable state — and writes one
immutable observation to Firestore.

The deployed collector has no UI and depends on no other application. Inspection
happens through terminal commands or an optional local-only dashboard; neither
is part of the scheduled runtime.

**Why sample a daily counter instead of reading power?** The official API exposes
no instantaneous power or wattage property for air conditioners. The state
resource carries `operation`, `temperatureInUnits`, `powerSave`, `airFlow`,
`airQualitySensor`, `filterInfo`, `windDirection`, and timer groups — and no
watts. The `DAILY` energy counter is the only energy signal available, so
sub-daily energy resolution means sampling it often and differencing
consecutive readings. That is the whole design in one sentence, and everything
below follows from it.

---

## Configuration

Every variable, all read from the environment (a local `.env` is loaded if
present and never overrides real environment variables).

| Variable | Required | Default | What it does |
|---|---|---|---|
| `LG_THINQ_PAT` | yes | — | ThinQ Personal Access Token. From Secret Manager when deployed. Never logged, never stored. |
| `LG_COUNTRY_CODE` | yes | — | Two-letter ISO 3166-1 code of the **LG account**. Selects the API region; `PH` routes to `KIC`. |
| `LG_CLIENT_ID` | yes | — | Generated **once** and reused forever. Startup fails rather than inventing one. |
| `LG_DEVICE_ID` | yes | — | Target device, from `airchive discover`. |
| `LG_ENERGY_PROPERTY` | yes | — | Energy property to poll. Must appear in the device's energy profile. |
| `LG_ENERGY_UNIT` | no | unset | Unit of the energy counter, for devices whose API reports none. Stored with `unitSource: "configured"`; a device-reported unit always wins. |
| `FIREBASE_PROJECT_ID` | yes | — | Project holding the telemetry database. |
| `POLL_INTERVAL_SECONDS` | no | `300` | Sampling cadence. Interval classification always uses *actual* observation times, never this. |
| `LG_DAY_TIMEZONE` | no | `Asia/Manila` | Timezone that defines the local day and the rollover boundary. Confirm it empirically — see [setup.md](setup.md) step 7. |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | no | unset | **Local escape hatch only.** Prefer ADC. Never set in the deployed service. |
| `AIRCHIVE_DASHBOARD_CACHE_PATH` | no | `~/.airchive/dashboard-cache.sqlite3` | Local dashboard's disposable SQLite projection cache. |

Startup validation runs before any network call or write, reports **every**
offending value at once, and never echoes a secret:

```
$ airchive poll --once
Invalid configuration:
  - LG_THINQ_PAT is required but missing or empty. Obtain it from the LG ThinQ developer portal.
  - LG_CLIENT_ID is required but missing or empty. Generate one once (...) and persist it; ...
```

---

## Running it

```bash
airchive --help              # every subcommand
airchive check-firestore     # storage round trip (Gate A)
airchive discover            # devices, profiles, energy property, unit, precision
airchive validate-counter    # does the daily counter advance intraday? (Gate B)
airchive poll --once         # one cycle, then exit
airchive poll                # a cycle per interval until interrupted
airchive serve               # request-triggered service on 0.0.0.0:$PORT
airchive latest --limit 20   # recent observations
airchive health              # collector health record
airchive anomalies --since 2026-08-20T00:00:00Z
airchive compare             # stored vs a fresh live reading
airchive dashboard           # local read-only Streamlit dashboard
```

Everything except `poll` and an accepted `serve` request is read-only. `compare`
in particular writes nothing to the telemetry series. No command ever issues a
device **control** command.

`poll --once` is the one-cycle implementation used by both deployment shapes:
all state is reconstructed from Firestore. `serve` accepts only `POST /poll` and
calls that same one-cycle path exactly once. It binds to `0.0.0.0:$PORT`, with a
default port of `8080`; Cloud Run IAM rejects unauthenticated requests before
the handler is reached. `poll` without `--once` runs a cycle per interval and
stops cleanly on SIGINT/SIGTERM, finishing or abandoning the cycle in flight so
no partial observation is left behind.

---

## Deployment

### Why a request-billed service rather than a long-running process

| | **Cloud Run Service + Scheduler** | Always-on service | Local process |
|---|---|---|---|
| Billing granularity | request duration, no one-minute floor; fractional CPU | pays 24/7 to idle | free, plus a machine that must never sleep |
| Restart behavior | every run is a cold start; no recovery path to get wrong | needs supervision and liveness | fails silently when the machine reboots |
| Credentials | attached service account, no key file | same | tempts a long-lived key on disk |
| State | already in Firestore, so statelessness costs nothing | in-memory state becomes a liability | same |
| Failure blast radius | one invocation | whole process | whole process |
| Observability | one request log stream; health and observations persist | needs its own | local only |
| Rate limits | same 2 calls per slot either way | same | same |

**Chosen: Cloud Run Service + Cloud Scheduler.** The service is request-triggered
and stateless: every cycle reconstructs its baseline from Firestore. That keeps
the same idempotent collector behavior while avoiding an always-on process. It
preserves the original job-over-always-on-service decision rather than reversing
it into an always-on service.

*Cost check:* before cutover, Cloud Run billing for 2026-09-01 through 2026-09-15
was $5.58 gross, with $4.61 covered by the free tier and $0.97 billed. The old
estimate ignored the one-minute billing floor and one-CPU assumption, so it is
not used as a budget baseline.

*Post-cutover measurement (checked 2026-09-21):* over 5.44 days after the
cutover, Cloud Monitoring reported 3,205.7 seconds of Cloud Run
`container/billable_instance_time` for 1,567 completed cycles. The billable unit
is request-active instance time rounded to 100 ms. At 0.5 vCPU this projects to
about 8.8k vCPU-seconds per 30-day month. Including the approximately 18k
vCPU-seconds/month used by `backlogium-steamapi-poller`, the projected shared
draw is about 26.8k, or 14.9% of the 180,000 request-based free allowance.

*Verified billing check (checked 2026-09-21):* the Cloud Billing report for the
2026-09-16 through 2026-09-21 charge period, filtered to this project and Cloud
Run and grouped by SKU, contains only request-based service SKUs. It reports
1,393.47 vCPU-seconds under `Services CPU Tier 2 (Request-based billing)`,
1,391.6 GiB-seconds of request-based memory, 1,321 requests, and zero GiB of
internet data transfer. No instance-based CPU SKU appears. The unrounded subtotal
is $0.047062 ($0.05 rounded). The filtered report shows no visible free-tier
credit, so the documented result is the actual subtotal rather than an assertion
that the service costs exactly $0. The relevant monthly allowances are 180,000
vCPU-seconds, 360,000 GiB-seconds, and two million requests per billing account.

Keep the service at 0.5 vCPU. Reducing it to 0.25 vCPU would save at most about
4.4k vCPU-seconds/month while the shared workloads already use less than 15% of
the CPU allowance; the extra latency and reduced CPU headroom are not justified.

### What is actually deployed


| | |
|---|---|
| Project | `airchive-telemetry-poller` |
| Region | `asia-southeast1` (same as Firestore) |
| Image | `asia-southeast1-docker.pkg.dev/airchive-telemetry-poller/airchive/collector:0.2.0` |
| Service | `airchive-poll-svc`, 512Mi / 0.5 vCPU, concurrency 1, min 0, 120s timeout |
| Collector identity | `airchive-collector@airchive-telemetry-poller.iam.gserviceaccount.com` - `roles/datastore.user` |
| Scheduler identity | `airchive-scheduler@airchive-telemetry-poller.iam.gserviceaccount.com` - `roles/run.invoker` on `airchive-poll-svc` |
| Secret | `lg-thinq-pat`, injected as `LG_THINQ_PAT` at runtime |
| Trigger | `airchive-poll-5min`, `*/5 * * * *`, Asia/Manila, OIDC `POST /poll` |

Two identities rather than one is deliberate. Cloud Scheduler needs
`run.invoker` to invoke the service; granting that to the collector would widen
an identity whose entire point is that it can do nothing but write telemetry.
Each service account holds exactly one role.

### Steps

```bash
PROJECT=airchive-telemetry-poller
REGION=asia-southeast1
IMAGE=$REGION-docker.pkg.dev/$PROJECT/airchive/collector:0.2.0
SERVICE=airchive-poll-svc
SCHEDULER=airchive-poll-5min
COLLECTOR_SA=airchive-collector@$PROJECT.iam.gserviceaccount.com
SCHEDULER_SA=airchive-scheduler@$PROJECT.iam.gserviceaccount.com

# 1. Build and push the image.
docker build --tag collector:0.2.0 .
docker tag collector:0.2.0 $IMAGE
docker push $IMAGE

# 2. A service account with exactly one role.
gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$COLLECTOR_SA" \
    --role="roles/datastore.user"

# 3. The request-triggered service. No key file: credentials come from the identity.
gcloud run deploy $SERVICE \
    --image=$IMAGE \
    --region=$REGION \
    --service-account=$COLLECTOR_SA \
    --set-secrets=LG_THINQ_PAT=lg-thinq-pat:latest \
    --set-env-vars=FIREBASE_PROJECT_ID=$PROJECT,LG_COUNTRY_CODE=PH,LG_CLIENT_ID=...,LG_DEVICE_ID=...,LG_ENERGY_PROPERTY=...,LG_DAY_TIMEZONE=Asia/Manila \
    --cpu=0.5 --memory=512Mi --concurrency=1 --min=0 --timeout=120s \
    --no-allow-unauthenticated

gcloud run services add-iam-policy-binding $SERVICE --region=$REGION \
    --member="serviceAccount:$SCHEDULER_SA" --role=roles/run.invoker

# 4. Every five minutes, with an OIDC token accepted by the service.
gcloud scheduler jobs update http $SCHEDULER \
    --location=$REGION \
    --schedule="*/5 * * * *" \
    --uri="https://SERVICE_URL/poll" \
    --http-method=POST \
    --oidc-service-account-email=$SCHEDULER_SA \
    --oidc-token-audience="https://SERVICE_URL"
```

The service has no unauthenticated ingress. The Scheduler identity is granted
`roles/run.invoker` only on this service, and the OIDC audience is the service
URL rather than the `/poll` path. Keep the generated service URL in the
Scheduler target and use the deployed image digest for a reproducible rollback.

The Artifact Registry repository has a `delete-untagged` cleanup policy. On
2026-09-21, the superseded `0.1.0` and `0.1.1` indexes and their four untagged
child manifests were removed after confirming the deployed revision uses the
`0.2.0` digest. `latest` now also names `0.2.0`. Repository size changed from
310.301 MB to 310.295 MB; the small reduction means the old releases shared
their large layer blobs with the retained image.

### Verifying a deployment

1. Check the service configuration and IAM: the service must be private,
   concurrency 1, min 0, and the Scheduler service account must have
   `roles/run.invoker` on this service.
2. Run the Scheduler once, then `airchive latest --limit 1` shows the new
   observation and `airchive health` shows a current `lastSuccessAt`.
3. Let three scheduled executions run. Confirm sequential sample IDs, roughly
   five-minute spacing, HTTP 200 request logs, and no negative intervals.


**Rollback** is pausing the Scheduler job or pointing it back to a known-good
service revision. Collected telemetry is append-only and unaffected; the next
run resumes from Firestore state and marks any gap `COARSE_INTERVAL`. There is
no destructive step to reverse.

---

## The stored data model

```
devices/{deviceId}                     identity, alias, model, metadata pointer
  telemetry/{sampleId}                 immutable observation series  <- source of truth
  dailyTotals/{localDate}              LG's finalized per-day totals (cached)
  metadata/{profileVersion}            versioned profile + energy-profile snapshots
  metadata/current                     pointer to the active profile version
  runtime/collector                    mutable health, overwritten in place
  runtime/reconciliation               bounded queue awaiting a finalized total
```

`sampleId` is the scheduled slot floored to the interval and stamped in UTC:
`20260820T091500Z` is the 17:15 Asia/Manila slot. UTC because the identifier must
stay unambiguous across DST and any later timezone change, and because it then
sorts lexicographically in the same order as chronologically.

One observation:

```json
{
  "sampleId": "20260820T091500Z",
  "deviceId": "...",
  "scheduledAt": "<timestamp>",   "observedAt": "<timestamp>",  "persistedAt": "<timestamp>",
  "localDate": "2026-08-20",      "timezone": "Asia/Manila",    "completeness": 3,
  "energy": {
    "property": "energyConsumption", "unit": "kWh", "unitSource": "device",
    "rawDailyTotal": "2.150",        "rawDailyTotalNumber": 2.15,
    "intervalValue": "0.050",        "intervalValueNumber": 0.05,
    "intervalSeconds": 300.0,
    "previous": { "sampleId": "...", "observedAt": "...", "localDate": "...",
                  "rawDailyTotal": "2.100", "rawDailyTotalNumber": 2.1 },
    "finalPreviousDayTotal": null,   "finalPreviousDayTotalNumber": null
  },
  "quality": { "intervalStatus": "NORMAL", "flags": [] },
  "source":  { "energy": {"ok": true, "failureClass": null, "errorCode": null, "errorName": null},
               "state":  {"ok": true, "failureClass": null, "errorCode": null, "errorName": null} },
  "state":   { "operation": {"airConOperationMode": "POWER_ON"}, "temperature": {"unit": "C"} },
  "raw":     { "energy": {...}, "state": {...} },
  "metadataVersion": "...", "collectorVersion": "0.1.0"
}
```

**The unit is stored with its provenance.** `energy.unitSource` is `"device"`
when the API reported the unit itself, and `"configured"` when it came from
`LG_ENERGY_UNIT` because the API reported none. Both are `null` when neither
exists. This matters more than it sounds: a counter stored as a bare `509` with
no unit is a number nobody can interpret in five years, and the obvious guess
(kWh) can be wrong by a factor of a thousand. Recording an operator-established
unit makes the series readable; recording *where it came from* keeps it from
ever being mistaken for something the device asserted.

**Decimal values are stored as strings, with a `…Number` float mirror
alongside.** Firestore has no decimal type, and a float is a binary
approximation: `8.751 - 8.732` in IEEE-754 is `0.019000000000000794`. The string
is authoritative — every derived number is recomputable from the stored strings
— and the mirror exists purely so range queries and aggregations work without
parsing every document.

**`raw.energy` and `raw.state` are the API's responses verbatim**, so the dataset
can be reinterpreted later against a better understanding of it. They contain
response content only: no request headers, no token, no credential of any kind.
They are exempted from indexing (`firestore.indexes.json`) because Firestore
otherwise indexes every nested scalar, and index storage would grow with LG's
payload shape rather than with anything we query.

**Ordering** keys on the mirrored `sampleId` field rather than the document key,
because Firestore rejects descending key scans outright. The value is identical,
so the chronological-sort property still holds, and the automatic single-field
index covers it.

---

## Interval and delta semantics

Interval consumption is the difference between the current cumulative reading
and the previous **usable** one, in `Decimal` throughout, quantized to the
precision the device itself reports.

Duration comes from the two readings' actual `observedAt` timestamps — never
from `POLL_INTERVAL_SECONDS`. If cycles were missed, the duration reflects that:
readings at 12:00 and 12:15 of 2.100 and 2.190 give 0.090 over ~900 seconds,
marked `COARSE_INTERVAL`, not 0.090 over a nominal 300.

Rules, each one preventing a specific wrong number:

| Situation | Interval | Status |
|---|---|---|
| Same day, counter advanced | difference | `NORMAL` |
| Same day, counter unchanged | `0` | `NORMAL` + `UNCHANGED_COUNTER` flag |
| Same day, more than 1.5× the cadence elapsed | difference | `COARSE_INTERVAL` |
| Same day, counter **decreased** | `null` | `ANOMALOUS_DECREASE` |
| No prior observation has ever existed | `null` | `NEW_BASELINE` |
| A prior observation exists but has no usable energy | `null` | `MISSING_PREVIOUS_SAMPLE` |
| Previous reading is from yesterday | reconstructed — see below | `DAY_ROLLOVER_*` |
| Previous reading is older than yesterday | `null` | `MULTI_DAY_GAP` |
| The energy request failed | `null` | `ENERGY_UNAVAILABLE` |

A decrease within a day is a provider revision, not negative consumption. The
earlier observation is never rewritten; the new one is stored with the
classification, so the revision stays visible in the historical series.

An observation whose energy request failed is never used as the baseline for the
next interval. The lookup walks back up to 12 documents to find a usable one, and
if it finds none it proceeds as `MISSING_PREVIOUS_SAMPLE` rather than using an
unusable one.

---

## Day rollover and reconciliation

At LG's midnight the counter resets, so subtracting across it would give a large
negative number. Instead:

```
crossDayDelta = (finalPreviousDayTotal − previousDailyValue) + currentDailyValue
```

— the unobserved remainder of yesterday plus today's accumulation so far, guarded
by `finalPreviousDayTotal >= previousDailyValue`.

Worked example: last reading yesterday 8.732, LG's finalized total for yesterday
8.751, first reading today 0.021 → `(8.751 − 8.732) + 0.021 = 0.040`, status
`DAY_ROLLOVER_RESOLVED`, with the finalized total stored on the observation.

When the finalized total is not available yet, the interval is left `null` with
`DAY_ROLLOVER_UNRESOLVED` and the sample is queued in `runtime/reconciliation`.
Later cycles retry — fetching the previous day's total at most once per cycle,
cached in `dailyTotals/{localDate}` so it costs one extra API call per day, not
one per cycle. When it arrives, the observation's **derived** fields are patched
and `RECONCILED` is added; the stored raw values are never touched.

Two ways it ends without a number:

- **Implausible total** — LG reports a "final" total *below* a value already
  observed that day. The reconstruction is refused, `IMPLAUSIBLE_FINAL_TOTAL` is
  flagged, and the value LG returned is recorded for inspection.
- **The 24-hour window closes** — reconciliation stops. The sample stays
  permanently unresolved, which is honest; a fabricated value would not be.

No reconstruction is attempted across more than one day boundary.

---

## The quality model

Three orthogonal things, never one overloaded field.

**`quality.intervalStatus`** — exactly one, explaining why `intervalValue` is
what it is:

| Status | Meaning |
|---|---|
| `NORMAL` | An ordinary same-day difference. |
| `NEW_BASELINE` | Nothing has ever been recorded for this device. |
| `MISSING_PREVIOUS_SAMPLE` | Records exist, but none carries a usable energy value. |
| `COARSE_INTERVAL` | Valid, but spans more than the nominal cadence. |
| `DAY_ROLLOVER_RESOLVED` | Reconstructed across midnight from the finalized total. |
| `DAY_ROLLOVER_UNRESOLVED` | Rollover detected, no trustworthy finalized total. |
| `ANOMALOUS_DECREASE` | The counter went backwards within a day. |
| `MULTI_DAY_GAP` | The baseline predates yesterday. |
| `ENERGY_UNAVAILABLE` | The energy request did not succeed. |

**`quality.flags`** — zero or more independent conditions, as an array so
`array-contains` makes each one queryable on its own:

| Flag | Meaning |
|---|---|
| `RATE_LIMITED` | ThinQ reported the call volume exceeded, or a cooldown suppressed the request. |
| `DEVICE_OFFLINE` | ThinQ reported the device as not connected. |
| `UNCHANGED_COUNTER` | The counter did not move; genuine idleness and provider latency are indistinguishable here. |
| `PARTIAL_OBSERVATION` | Exactly one of the two sources succeeded. |
| `RECONCILED` | A deferred interval was filled in later. |
| `IMPLAUSIBLE_FINAL_TOTAL` | The finalized previous-day total could not be true. |

**`source.energy` and `source.state`** — the outcome of each request,
independently, with the failure class and error code. A failed source is a
property of that source, not of the arithmetic, so it never lands in
`intervalStatus`.

A coarse interval that was also rate limited records **both**: neither displaces
the other, and neither displaces the status. Energy and state are independent —
one failing never discards the other's result, and nothing is ever carried
forward from a previous observation to fill a gap.

### Failure classes

Classification keys on ThinQ's error codes, because the SDK discards the HTTP
response and status is not observable.

| Class | Triggered by | Response |
|---|---|---|
| `RATE_LIMITED` | `1305`, `1306`, `1309` | Backoff with jitter, then a cross-cycle cooldown |
| `AUTH_FATAL` | `1103`, `1218`, `1301`, `1302` | **No retry.** Replace the token |
| `DEVICE_OFFLINE` | `1222` | Not a collector fault; recorded as unavailability |
| `TRANSIENT` | `2000`, `2209`, `2210`, `2212`, `2214` | Bounded retry within the cycle |
| `CONFIG_FATAL` | `1205`, `1212`, `1213`, `1219`–`1221`, `1224`, `1307` | No retry; surfaced loudly |
| `MALFORMED` | Non-JSON body, unexpected structure | Recorded; never crashes the process |
| `TRANSPORT` | Connection errors, timeouts | Bounded retry |
| `UNKNOWN` | Any unmapped code | Recorded, not retried |

---

## Idempotency

Sample identity is the slot, so re-running a slot reconciles rather than
duplicates. Writes are transactional and follow completeness precedence, where
`completeness = 2×(energy ok) + 1×(state ok)`:

| Situation | Result |
|---|---|
| No document for the slot | created |
| The retry is more complete | upgraded |
| The retry is equally complete | no-op — first writer wins, `observedAt` does not churn |
| The retry is less complete | refused, and the refusal is logged |
| Reconciliation | patches derived fields only; never touches raw values |

Deterministic identifiers alone would prevent duplicate *creation* while opening
a stale-overwrite hazard: a delayed retry for slot T could clobber a better
record written since. Precedence closes that, which is what makes replay safe on
a runtime that occasionally double-delivers.

Two cycles that overlap are prevented by a short advisory lease on
`runtime/collector.leaseUntil`. A cycle that cannot take the lease exits without
writing; the gap it leaves is handled as `COARSE_INTERVAL`, which has to work
anyway.

---

## Inspection commands

```
$ airchive latest --limit 3
sampleId           observedAt                   raw   interval     dur  intervalStatus     sources
20260820T091000Z   2026-08-20 09:10:00Z       2.200      0.050    300s  NORMAL             energy=ok state=ok
20260820T090500Z   2026-08-20 09:05:00Z       2.150      0.050    300s  NORMAL             energy=ok state=ok
20260820T090000Z   2026-08-20 09:00:00Z       2.100          —       —  NEW_BASELINE       energy=ok state=ok
```

`health` prints the current health record and any pending reconciliations.
`anomalies --since ... --until ...` returns observations whose status or flags
indicate a problem (defaults to the last 24 hours). `compare` diffs the newest
stored observation against a fresh live reading, marking differing fields with
`*`, and writes nothing.

The Firestore console remains usable for visual confirmation: raw payloads are
stored as readable maps rather than JSON strings specifically so they can be
spot-checked there.

---

## Local dashboard

The optional Streamlit wrapper presents the same stored data visually without
opening Firestore to browser clients:

```bash
# These are the only required application settings. Authenticate separately
# with Application Default Credentials as described in setup.md.
FIREBASE_PROJECT_ID=lg-ac-telemetry
LG_DEVICE_ID=your-device-id
LG_DAY_TIMEZONE=Asia/Manila

airchive dashboard
```

The supported launcher binds Streamlit to `127.0.0.1`. It is deliberately a
single-user local tool, not a remotely hosted service, and it never sends Google
credentials to the browser. It needs no ThinQ token because it reads only stored
Firestore data. Viewing, filtering, refreshing, loading raw details, and clearing
the cache perform no Firestore write and no device control operation.

The first view covers 24 hours; 7-day and 30-day ranges are available explicitly.
The dashboard refreshes no faster than `POLL_INTERVAL_SECONDS` (five minutes by
default), or when **Refresh now** is pressed. Charts leave null intervals as gaps,
and totals always show usable-slot coverage so missing data is never counted as
zero.

### Cache behavior

Normalized fields used by cards, charts, and tables are cached in a user-local
SQLite file. By default it is:

```text
~/.airchive/dashboard-cache.sqlite3
```

Set `AIRCHIVE_DASHBOARD_CACHE_PATH` to override that location. Once a time range
has been covered, revisiting it reads SQLite and performs only incremental
Firestore checks for newly persisted, completeness-upgraded, or reconciled
observations. Raw energy/state payloads are excluded from SQLite and fetched only
after **Load raw payload** is pressed; that result remains short-lived in the UI
session.

If Firestore is unavailable, the last valid cached data remains visible with its
sync age and a stale warning. If SQLite fails its integrity or schema check, the
invalid file is moved beside the cache with a `.corrupt-<timestamp>` name and a
new cache is created. **Cache controls → Clear local cache** requires confirmation
and deletes only this disposable local projection; Firestore is never changed.

---

## Collector health

`devices/{deviceId}/runtime/collector`, overwritten in place, never appended to
the series and never used as an analytics source:

| Field | Meaning |
|---|---|
| `lastAttemptAt` | Start of the most recent cycle |
| `lastSuccessAt`, `lastSampleId`, `lastSamplePath` | The most recent cycle that stored something |
| `lastErrorAt`, `lastErrorClass`, `lastErrorMessage` | The most recent failure |
| `consecutiveFailures` | Increments per failed cycle, resets to 0 on success |
| `consecutiveRateLimits`, `rateLimitedUntil` | Cross-cycle rate-limit cooldown |
| `leaseUntil`, `leaseHolder` | The overlap-prevention lease |
| `collectorVersion` | Which build wrote it |

For a request-triggered service, health and observation evidence are the
liveness source; platform execution records are not. A failed invocation
can still advance `lastAttemptAt`, while `lastSuccessAt` remains stale. If both
timestamps stop advancing, inspect Scheduler and Cloud Run service logs before
assuming a device problem.

Worth alerting on: no completed-cycle evidence for 30 minutes, and
`consecutiveFailures` climbing with `lastErrorClass` equal to `AUTH_FATAL` or
`CONFIG_FATAL`. Those fatal classes never recover on their own.

---

## Rate limiting

ThinQ signals rate limiting in-band via error codes; there is no `Retry-After`
to read, because the SDK discards the HTTP response. So:

1. Within a cycle, a rate-limited request backs off exponentially with ±50%
   jitter, bounded in both attempts and total time.
2. Across cycles, `consecutiveRateLimits` drives a cooldown (10 minutes,
   doubling, capped at an hour) recorded in health. A cycle starting inside the
   cooldown issues **no requests at all** — that is what reduces the effective
   rate rather than merely re-pacing it. It still writes an observation, flagged
   `RATE_LIMITED`, so the outage is visible in the series.
3. The first successful cycle clears the cooldown and normal cadence resumes.

A routine cycle costs exactly two API calls, so one device is ~576 calls a day,
plus one extra on each day boundary for the previous day's finalized total.

---

## Alerting

The collector fails *quietly* by design — a cycle that cannot reach LG records
the failure and returns, rather than crashing. That is right for resilience and
wrong for attention: without alerting, the most likely way this project loses
history is an expired token, nobody noticing for a month, and thirty days that
cannot be recreated.

Two policies close that, both notifying `paulandretadiar012703@gmail.com`:

| Policy | Fires when | Why it matters |
|---|---|---|
| **Collector has stopped producing observations** | No completed service cycle for 30 minutes, against a 5-minute schedule | Catches everything that stops execution outright: Scheduler disabled, service broken, billing lapsed, image unpullable |
| **Fatal condition, collection will not resume on its own** | `AUTH_FATAL`, `CONFIG_FATAL`, or any `ERROR`-severity cycle log | These are deliberately never retried, so nothing else will surface them |

The first rests on a log-based metric, `airchive_cycle_success`, counting
`cycle complete` records emitted by the collector. Its absence is independent
of platform execution records. The second matches structured collector log fields
directly — no code change was needed to enable it, because the runtime spec
already required every cycle to log its per-source failure classes.

Both alert emails carry their own runbook. The fatal one includes the token
rotation, which is the case it will most often be reporting:

```bash
printf '%s' "$NEW_PAT" | gcloud secrets versions add lg-thinq-pat --data-file=-
```

The service reads `lg-thinq-pat:latest`, so the next scheduled cycle picks up a
new version with no redeploy.

The absence path was exercised during cutover with a temporary policy using the
same `airchive_cycle_success` metric and `cloud_run_revision` resource. Cloud
Monitoring opened the alert at 2026-09-15 18:38:11 UTC and closed it at
18:38:44 UTC after cycle evidence resumed. This proves a stalled invocation is
reportable. An invoked-but-failing cycle is distinct: `lastAttemptAt` advances
while `lastSuccessAt` remains stale, `consecutiveFailures` increases, and the
fatal-condition policy reports its collector-written failure class or error log.

**What is deliberately not alerted:** `DEVICE_OFFLINE`, `RATE_LIMITED`,
`UNCHANGED_COUNTER`, coarse intervals, and unresolved rollovers. Each is a
normal, self-correcting condition that the series already records. Paging on
them would train you to ignore the alerts that matter. Query them with
`airchive anomalies` instead.

---

## Credential hygiene

`ThinQAPIException` is constructed by the SDK with the **outbound request
headers**, which contain `Authorization: Bearer <PAT>`. Any ordinary
`logger.exception(...)`, structured logger walking `__dict__`, or error-reporting
integration would put the token into retained logs. This is the default
behaviour of ordinary code against this specific exception type, not a
hypothetical.

The mitigation is structural. One module touches the SDK. It converts every
exception into a `ThinqFailure` carrying only the failure class, code, error
name, and a safe message, and re-raises it in a way that leaves the original
unreachable through `__cause__` *or* `__context__`. A registered-secret scrubber
backs that up on every log record and printed line. Tests assert a sentinel token
appears in no rendered log record, no formatted traceback, no serialized
failure, and no command's output.

Beyond that: no key file in the image, no key file in the repository, Firestore
client rules denied, `roles/datastore.user` and nothing more, and the PAT from
Secret Manager at runtime.

---

## Known device and API limitations

Each of these is a fact about LG's API or SDK, established by reading
`thinqconnect` 1.0.13 or by discovery against the real device.

- **No instantaneous power property.** The AC state resource has no watts. The
  `DAILY` counter is the only energy signal, which is why the whole design is
  "sample a cumulative counter often".
- **HTTP status is invisible.** `async_request` returns `payload["response"]` and
  discards the `ClientResponse`, so status codes and `Retry-After` never reach
  us. Failure classification keys on ThinQ error codes instead.
- **Errors carry the bearer token.** See [credential hygiene](#credential-hygiene).
- **A non-JSON error body raises a different exception.** `await response.json()`
  is called *before* the `response.ok` check, so a gateway HTML page or an empty
  502 surfaces as `aiohttp.ContentTypeError`, not `ThinQAPIException`. Both are
  handled.
- **The device wrapper is coupled to the process clock.** `ConnectBaseDevice.get_daily_energy_usage()`
  validates dates against `date.today()` — the *system-local* date — and raises
  `ValueError` when `today < end_date`. A UTC-clocked container asking for
  Manila's "today" would fail for the first eight hours of every Manila day,
  precisely when rollover reconciliation runs. This collector uses the low-level
  `ThinQApi`, which performs no such check; a test demonstrates both the coupling
  and its absence from our path.
- **Firestore rejects descending key scans.** "Latest sample is a descending key
  scan" does not work; ordering uses the mirrored `sampleId` field instead.
- **The SDK eagerly imports its MQTT client.** `thinqconnect/__init__.py` imports
  `mqtt_client`, pulling `awsiotsdk` and `pyOpenSSL` — roughly 430 ms and 400
  modules on every cold start for functionality this collector does not use.
  Importing a submodule does not avoid it. Unavoidable while using the official
  SDK; the mitigation is a slim base image.
- **The energy response shape is read defensively.** The extractor locates the
  numeric reading under the names ThinQ plausibly uses and returns *nothing*
  rather than a guess when it cannot. It will never attribute another day's value
  to the requested day. Record the real shape in
  [discovery-findings.md](discovery-findings.md) once observed.
- **The energy counter may carry no unit at all.** The tested device
  (`WIN_056905_WW`) returns a bare integer with no unit field anywhere in the
  response, so the API alone cannot say whether `509` is watt-hours or
  kilowatt-hours. Establish it by comparing a stored raw value against the LG
  ThinQ app's own kWh figure for the same day, then set `LG_ENERGY_UNIT`. See
  [discovery-findings.md](discovery-findings.md).
- **Which state properties this model populates is device-specific.** The
  collector stores exactly what the device returns and invents nothing. Anything
  the profile does not expose is simply absent — see the discovery findings.

---

## Storage growth

~288 observations a day, ~105,000 a year, at roughly 2–4 KB each (raw payloads
dominate) → **about 300–450 MB a year**. Firestore's 1 GiB free tier covers
roughly two years. Write volume is negligible; storage is the eventual cost
driver, which is why raw payloads are exempted from indexing.

When it matters, the options are export to GCS or BigQuery, or a cold-storage
tier for older years. Whichever is chosen, **raw observations are never deleted
or downsampled in place.** Any archival mechanism must preserve the raw series
in a durable form; the high-resolution history is the thing that cannot be
recreated.

---

## Future enhancements

- **ThinQ MQTT / event subscription.** The SDK supports push notification and
  event subscription, which would give finer resolution on *state changes* than
  five-minute sampling. It is explicitly **not** used or required here: the
  collector relies on periodic sampling only, and nothing in the implementation
  depends on MQTT. (Its transitive dependencies are dead weight in the image, as
  noted above.)
- **A second device.** The data model is keyed per device, so another device is
  additive, but the runtime targets one. Multi-device orchestration is
  deliberately unbuilt.
- **Aggregation and analytics.** Out of scope by design. The raw series is the
  source of truth and any later rollup derives from it.

---

## Testing

```bash
python -m pytest -q                      # everything, offline, no credentials
python -m ruff check src tests

# The persistence rules again, against a real Firestore:
firebase emulators:exec --only firestore --project demo-airchive \
    ".venv\Scripts\python.exe -m pytest tests/test_store_emulator.py -q"
```

The offline suite substitutes both external systems: a scripted ThinQ API that
records every call, and an in-memory Firestore that models transaction retries
under concurrent writes. Deltas, classification, idempotency, restart recovery,
backoff, and shutdown are all verified without a live service. The emulator
suite re-checks the persistence rules against the real client library — it is
what caught the descending-key-scan assumption.
