## Context

See [proposal.md](proposal.md) for motivation and the delta specs for the required behavior. On 2026-09-21, the live `airchive-poll-svc` and the default Firestore database were both confirmed in `asia-southeast1` (Singapore). The service uses request-based billing, 0.5 vCPU, 512 MiB, concurrency 1, minimum instances 0, and a private Scheduler-triggered `POST /poll`. `docs/operations.md` records $0.047062 in Cloud Run charges over 2026-09-16 through 2026-09-21, but its project-filtered SKU report shows no visible free-tier credit. This is evidence of a residual bill, not proof that Tier 2 placement is its only cause.

Google lists `asia-east1` (Taiwan) in Cloud Run Tier 1 and `asia-southeast1` in Tier 2. Cloud Run's request-based free allowance is shared by billing account and applied as a spending discount at Tier 1 prices. Firestore location cannot be changed in place; cross-region Firestore responses can be billed, subject to the published network free allowance. A new named Firestore database would not preserve the existing default database's free quota. Verify current prices and terms before implementation: [Cloud Run pricing](https://cloud.google.com/run/pricing), [Firestore locations](https://docs.cloud.google.com/firestore/native/docs/locations), [Firestore pricing](https://cloud.google.com/firestore/pricing).

## Goals / Non-Goals

**Goals:** Determine whether a Tier 1 Cloud Run location can materially reduce Airchive's total monthly bill, with zero as an aspiration rather than a guarantee. If evidence supports the move, preserve collection correctness, privacy, schedule, and a quick rollback; measure the result from billing rather than a quota estimate.

**Non-Goals:** Relocating Firestore or creating a second database; changing the 300-second sampling cadence, telemetry model, CPU allocation, collector code, or ThinQ integration solely to force a zero bill. No deletion of the Singapore service until the candidate is proven and the rollback window is closed.

## Decisions

### D1: Diagnose the current bill before deploying another region

Read a complete billing-account report, plus the Airchive-project breakdown grouped by service, SKU, region, and credits. Check whether the September subtotal reflects a Tier 2 premium, free-tier credit assignment to another project, delayed credit reporting, or another service. Compare a full settled billing period where available. Derive a conservative candidate estimate using current Tier 1 rates and include all affected SKUs. If Tier 1 cannot plausibly improve total cost, record a no-go decision and leave the deployment unchanged.

*Alternative considered:* assume the $0.047062 is entirely a Tier 2 premium and redeploy immediately. Rejected because the filtered report showed no visible credit and does not establish that assumption.

### D2: Move only Cloud Run, initially to `asia-east1`

Taiwan is a Tier 1 Cloud Run region relatively close to the Singapore Firestore database. Keep the same project, collector identity, secret, image digest, resource limits, request-based billing, private ingress, and OIDC authentication. The Scheduler job can remain in its current region while targeting the new HTTPS service URL. Confirm image availability and any Artifact Registry transfer charge before choosing whether to pull from Singapore or copy the image nearer the service.

*Alternative considered:* move Firestore too, for colocation. Rejected for this change: the existing database's location is immutable, data migration introduces continuity risk, and a second database can lose the current free quota.

### D3: Use a reversible, single-target cutover

Deploy a separate private service in Taiwan. Grant the existing Scheduler identity `roles/run.invoker` only on the candidate service as needed. Exercise a single authorized request and confirm one new observation and health advancement. Record the old Scheduler URI and audience, then update the existing five-minute Scheduler job to the new service URL and its OIDC audience. Never leave both regions scheduled. Watch at least three scheduled cycles for failures, duplicate/negative intervals, and latency. Keep the Singapore service available for rollback while billing evidence accumulates.

*Alternative considered:* delete/recreate the old service immediately. Rejected because it removes the fast rollback path for a small expected saving.

### D4: Treat the zero-bill claim as a post-cutover finding

Compare 48+ hours of settled post-cutover Airchive SKUs with the baseline, and revisit after the next complete billing month. Include Cloud Run CPU, memory, requests, free-tier credits, Firestore network transfer, Scheduler, Artifact Registry, and any other charged service. Check the billing account's shared allowance, not just the Airchive project. A $0 Cloud Run line is not the same as a $0 total bill. Record the measured result and any remaining uncertainty in `docs/operations.md`; retain the existing $1 budget alert.

*Alternative considered:* declare success when Cloud Run usage falls under the published free quota. Rejected because the current measured bill already contradicts that inference.

## Risks / Trade-offs

- Cross-region Firestore reads add latency and may add egress cost -> compare cycle duration and Firestore network SKUs before/after; roll back if the cadence or total-cost goal is harmed.
- Shared free-tier credits may be consumed elsewhere or appear later -> inspect billing-account credits and use settled reports; never promise a guaranteed zero month.
- A wrong Scheduler URI or OIDC audience stops collection -> save the previous values, test the new service before retargeting, monitor health and observations, and restore the old target immediately on failure.
- Two services can trigger duplicate polls if both scheduled -> retain exactly one Scheduler job and one active target; do not add a second periodic trigger.
- Image location or secret permissions may differ across regions -> inspect service deployment and IAM before cutover; avoid changing collector behavior as part of this experiment.

## Migration Plan

1. Capture the current Singapore service, Scheduler target/audience, IAM, image digest, Firestore location, cycle-health baseline, and settled bill by SKU and credit.
2. Recheck official pricing and estimate the whole-project effect of a Taiwan service; document the go/no-go result. Stop without infrastructure changes if the move is not plausibly beneficial.
3. Deploy a separate private Taiwan service with equivalent configuration and invoke it once manually; verify a normal persisted observation and health update.
4. Retarget the existing Scheduler job to the Taiwan URL with the matching OIDC audience. Verify three consecutive scheduled cycles and no overlapping regional schedules.
5. Compare latency, failures, and billing after at least 48 hours of reported usage. Roll back if health or total-cost criteria fail. After the next complete billing month, record whether the total bill was actually zero.
6. Only after evidence and an explicit operational decision, retire the unused regional service and stale IAM binding; update `docs/operations.md` with the deployed state and rollback procedure.

**Rollback:** restore the saved Singapore Scheduler URI and OIDC audience, confirm its `run.invoker` binding, invoke/check the service, and verify that observation and health timestamps advance on the next scheduled cycles. Stop scheduling Taiwan before any cleanup.
