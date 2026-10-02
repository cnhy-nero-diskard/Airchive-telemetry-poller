## Why

The deployed collector runs as a Cloud Run **Job**, and Cloud Run bills jobs for the entire lifetime of the instance started, **with a minimum of one minute**. A poll cycle takes roughly 18 seconds, so every one of the 288 daily executions is billed as 60 — about 3.3× the compute actually consumed. That is ~525,000 vCPU-seconds per month against the 240,000 vCPU-second instance-based free allowance, and it produced the project's first real invoice: $5.58 of gross Cloud Run usage between 1–15 September 2026, of which $4.61 was absorbed by the free tier and $0.97 billed.

The cost check recorded in `docs/operations.md` when the topology was chosen estimated "8,640 executions/month × ~5 s ≈ 43k vCPU-seconds against a 180k free tier". Three things in that sentence are wrong: a cycle takes ~18 s rather than ~5 s, jobs bill a 60 s floor rather than actual duration, and jobs draw on the 240k instance-based allowance rather than the 180k request-based one. The estimate was low by roughly 12×, which is why the overrun was invisible until it was billed.

The obvious mitigation — lowering the CPU allocation — is unavailable. Cloud Run jobs run only on the gen2 execution environment, and gen2 rejects any CPU value below 1 when CPU is always allocated. Both were confirmed against the live job:

```
ERROR: Total cpu < 1 is not supported with gen2 execution environment with cpu always allocated (unthrottled).
ERROR: Annotation 'run.googleapis.com/execution-environment' with value 'gen1' is not supported on resources of kind Execution.
```

The remaining lever, lengthening the poll interval, is explicitly rejected by [discovery-findings.md](../../../docs/discovery-findings.md): LG refreshes the daily counter every ~303 s median, the 300 s cadence is matched to it, and "the resolution is the point of the project".

A request-billed Cloud Run **Service** removes both constraints at once. It is billed for actual request duration with no one-minute floor, and it permits fractional CPU. At 0.5 vCPU the collector draws ~80,000 vCPU-seconds per month against the 180,000 request-based allowance — inside the free tier with real margin, at the same five-minute cadence.

Critically, this does not reverse the original topology decision. The "always-on service" rejected in `docs/operations.md` is not what this is: with minimum instances at zero the collector remains stateless, still cold-starts on every invocation, still reconstructs its baseline from Firestore, and still confines a failure to a single invocation. Every criterion that selected the job is preserved. Only the billing meter and the trigger mechanism change.

## What Changes

- Add an HTTP entry point that runs exactly one poll cycle per request, wrapping the existing `poll --once` path rather than reimplementing it.
- Deploy the collector as a Cloud Run **Service** at 0.5 vCPU with minimum instances zero, concurrency 1, and request-based billing; retire the `airchive-poll` Job.
- Retarget the existing `airchive-poll-5min` Cloud Scheduler trigger from the Jobs API to the service URL, authenticated with an OIDC token.
- Move the `roles/run.invoker` binding held by `airchive-scheduler@…` from the job to the service. The collector identity keeps `roles/datastore.user` only; the two-identity split is unchanged.
- Decouple liveness detection from job executions. The "no completed cycle for 30 minutes" signal currently keys on Cloud Run Job execution records, which cease to exist; it must key on the collector health record and observation recency instead.
- Correct the falsified cost check in `docs/operations.md`, and record billing granularity — the minimum billable unit — as a criterion in the deployment topology evaluation, so a future topology choice cannot repeat this error.
- **Not changing**: the 300 s cadence, the telemetry schema, interval and day-rollover semantics, Firestore rules, the dashboard, or the ThinQ integration.

## Capabilities

### New Capabilities

None. The collector's observable telemetry behavior is unchanged; what changes is how it is invoked and how the topology decision is justified.

### Modified Capabilities

- `collector-runtime`: The deployment topology criteria gain billing granularity, and the recorded cost basis must be verified against actual billed usage rather than estimated wall-clock duration. Adds a requirement that the collector is invocable through an authenticated request interface that runs exactly one cycle and holds no state between invocations.
- `collector-operations`: Liveness detection must not depend on any particular execution primitive, and operator documentation must record a cost basis that has been checked against real billing.

## Impact

- **Code**: adds an HTTP entry point module and its wiring; changes the container entrypoint in `Dockerfile` to serve rather than run once. The cycle, observation, storage, and ThinQ layers are untouched.
- **Infrastructure**: new Cloud Run service; `airchive-poll` job deleted after cutover; scheduler target and OIDC audience changed; one IAM binding moved.
- **Cost**: ~$5/month → $0, at ~44% of the request-based free allowance. Combined with `backlogium-steamapi-poller`, which draws ~18,000 vCPU-seconds/month from the same per-billing-account pool, total use is ~55% of 180,000.
- **Docs**: `docs/operations.md` deployment section, topology table, cost check, and collector-health section.
- **Risk**: an unauthenticated service URL would expose the collector to arbitrary triggering. OIDC authentication and `run.invoker` scoped to the scheduler identity are load-bearing, not optional hardening.
- **Migration**: the series is append-only and every cycle reconstructs its baseline from Firestore, so a brief gap across cutover is absorbed as a `COARSE_INTERVAL` and needs no backfill.
