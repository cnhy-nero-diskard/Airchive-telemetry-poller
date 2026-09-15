## Context

See [proposal.md](proposal.md) for motivation. The constraints that shape the approach:

- `poll_cmd.run(once=True)` already performs exactly one cycle and returns an exit code. The cycle, observation, storage and ThinQ layers need no change; only the way that function is reached does.
- The `Dockerfile` states its own philosophy in a comment: the `thinqconnect` import costs ~430 ms on every one of ~288 daily cold starts, "so the base image is the one place left to keep the invocation cheap." Any new dependency is paid 288 times a day.
- Request-based billing changes the optimisation target. Under the job's 60-second floor, wall-clock duration below 60 s was free; under request-based billing every second is charged, so latency and cost are now the same axis.
- The request-based free allowance is **per billing account** and is shared with `backlogium-steamapi-poller`, which draws ~18,000 vCPU-seconds/month from it.
- Fractional CPU requires maximum concurrency of 1 — which this workload wants anyway.

## Goals / Non-Goals

**Goals:**

- Reach $0 recurring cost with margin, at the unchanged 300 s cadence.
- Keep the collector stateless and the failure blast radius at one invocation.
- Keep `airchive poll --once` working unchanged for local runs and tests.
- Leave a cost basis in the docs that is checked against real billing.

**Non-Goals:**

- Reducing the ~14 s of I/O wait against the LG and Firestore APIs. That is the dominant term and is not this change's problem.
- Any change to telemetry schema, interval semantics, day-rollover handling, or the dashboard.
- Making the collector generally HTTP-addressable. The entry point triggers a cycle and nothing else.

## Decisions

### D1: A Cloud Run Service with request-based billing, not a job

Jobs bill the instance lifetime with a 60-second minimum and are hard-floored at 1 vCPU (gen2 rejects fractional CPU; jobs reject gen1 — both confirmed against the live job). A request-billed service bills actual request duration and permits fractional CPU. Those are the only two levers available, and the service form unlocks both.

*Alternatives considered:* lengthening the cadence — rejected by `discovery-findings.md`, which matched 300 s to LG's ~303 s median refresh. Accepting ~$5/month — defensible, but the fix is small and bounded. Moving off Cloud Run entirely — a much larger change for the same outcome.

### D2: The HTTP layer is `http.server` from the standard library, not a web framework

Flask or FastAPI plus an ASGI server would add import cost to every cold start, against a Dockerfile whose stated purpose is to avoid exactly that. The surface required is one authenticated POST route with no routing, no serialisation, no middleware. `http.server` covers it with zero new dependencies.

*Alternative considered:* FastAPI + uvicorn, for the ecosystem. Rejected — nothing in that ecosystem is needed here, and cold start is now directly billable.

### D3: Concurrency 1, minimum instances 0

Concurrency 1 is required for fractional CPU and independently correct: it preserves the existing guarantee that a cycle overrunning its interval does not pile up. Minimum instances 0 preserves statelessness — every invocation cold-starts and reconstructs its baseline from Firestore, exactly as the job did. This is what keeps the original topology decision intact rather than reversing it into the "always-on service" that `docs/operations.md` rejected.

### D4: Start at 0.5 vCPU, measure, then consider 0.25

The cycle is I/O-bound: roughly 4 s of CPU (interpreter start plus imports) against roughly 14 s of network wait. Modelling wall time as `14 + 4/c`:

| CPU | modelled wall time | vCPU-s per cycle | vCPU-s/month |
|---|---|---|---|
| 1.0 | ~18 s | 18 | ~158,000 |
| 0.5 | ~22 s | 11 | ~96,000 |
| 0.25 | ~30 s | 7.5 | ~66,000 |

Lower CPU is monotonically cheaper because the dominant term is I/O wait that does not scale with CPU. It is not monotonically *safer* — latency grows, and the model is an estimate. Land on 0.5 (comfortably inside the allowance even with backlogium's draw), measure real durations, and only then decide whether 0.25 is worth the added latency. Note 0.25 vCPU caps memory at 512 MiB, which is exactly the current allocation.

### D5: Authentication is OIDC from the scheduler identity, and it is load-bearing

The service is not public. Cloud Scheduler presents an OIDC token; `roles/run.invoker` is granted to `airchive-scheduler@…` on the service alone. This mirrors the existing job arrangement, where the scheduler identity holds only `run.invoker` and the collector identity only `roles/datastore.user`. An unauthenticated service URL would let anyone trigger cycles and burn the ThinQ rate budget, so this is not optional hardening.

### D6: Liveness detection moves onto evidence the collector writes

The "no completed cycle for 30 minutes" signal currently keys on Cloud Run Job execution records, which stop existing at cutover. It must key on the collector health record and observation recency instead — data the collector writes itself, which survives any future change of execution primitive. Deleting the job before this moves would silently disable the only alert that catches the collector stopping outright.

### D7: The CLI stays the source of truth

The HTTP handler calls `poll_cmd.run(once=True)` and translates its exit code into a status. It adds no logic of its own. `airchive poll --once` keeps working for local runs, and the existing tests keep covering the cycle through the same path.

## Risks / Trade-offs

- **Cutover leaves a gap in the series** → The series is append-only and each cycle rebuilds its baseline from Firestore, so a missed slot is absorbed as a `COARSE_INTERVAL`. No backfill needed; verify one appears rather than a negative interval.
- **The job is deleted before the service is proven** → Keep the job deployed but untriggered until three consecutive service cycles succeed. Rollback is re-pointing the scheduler at the job.
- **Scheduler retries stack cycles** → Concurrency 1 plus the existing overrun protection. Keep scheduler retries conservative; a missed slot is cheaper than a pile-up.
- **Latency grows at reduced CPU until a cycle exceeds the cadence** → Set the service request timeout well below 300 s and alert on cycle duration, not just failure. The 300 s cadence gives ample headroom against a ~22 s cycle, but the margin shrinks as CPU drops.
- **The free allowance is shared and can be exhausted by the other project** → `backlogium-steamapi-poller` draws ~18,000 vCPU-s/month from the same per-billing-account pool. The recorded cost basis must include it, and a budget alert should exist independently of this change.
- **`openspec/specs/` is empty, so the MODIFIED deltas here have no base to merge into** → `add-lg-aircon-telemetry-poller` and `add-lightweight-ui-wrapper` are still unarchived; their requirements live only in their own change folders. This change's `MODIFIED` blocks carry full requirement text, so they are self-describing, but `add-lg-aircon-telemetry-poller` must be synced into `openspec/specs/` before this change is archived or the modifications will have nothing to apply against.

## Migration Plan

1. Build and push a new image with the HTTP entry point. The image still supports `poll --once`, so it is safe on the existing job.
2. Deploy the Cloud Run service at 0.5 vCPU / 512 MiB, concurrency 1, min instances 0, no unauthenticated access.
3. Grant `roles/run.invoker` on the service to `airchive-scheduler@…`.
4. Invoke once manually with an OIDC token; confirm a normal observation lands in Firestore and the health record updates.
5. Retarget `airchive-poll-5min` to the service URL with OIDC. Leave the job in place, untriggered.
6. Observe three consecutive cycles. Confirm no negative interval and at most one `COARSE_INTERVAL` across the cutover.
7. Move the liveness alert onto health-record and observation recency before the job is removed.
8. Delete the `airchive-poll` job and revoke the scheduler's `run.invoker` on it.
9. After 48 hours, read actual billed Cloud Run usage and record the verified cost basis in `docs/operations.md`, replacing the falsified estimate.

**Rollback:** at any point before step 8, re-point `airchive-poll-5min` at the job. The job is unchanged and the image is backward compatible, so rollback is one scheduler edit.
