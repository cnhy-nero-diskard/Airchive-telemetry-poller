## 1. Establish the cost and health baseline

- [ ] 1.1 Confirm the live Cloud Run, Scheduler, Firestore, image, IAM, and secret configuration; record the Singapore service URL, Scheduler URI and OIDC audience, image digest, and database location in the handoff evidence, verifying each against live resource descriptions.
- [ ] 1.2 Export a settled billing-account and Airchive-project report grouped by service, SKU, region, and credits; identify why the 2026-09-16 through 2026-09-21 Cloud Run subtotal showed no visible credit, and verify the explanation against the report rather than assuming Tier 2 alone caused it.
- [ ] 1.3 Record a pre-move baseline for completed cycles, failures, billable instance time, request duration, Firestore network usage, and all Airchive charges; verify the date ranges and units are explicit.
- [ ] 1.4 Recheck current official Tier 1/Tier 2 and Firestore transfer pricing and estimate the total monthly effect of `asia-east1`, including the billing-account-wide free-tier draw; document a go/no-go decision, verifying it does not claim guaranteed $0 from quota math alone.

## 2. Prepare a reversible candidate if the evidence supports a move

- [ ] 2.1 If the decision is go, deploy a separate private `asia-east1` Cloud Run service from the pinned image with the same identity, secret, environment, CPU, memory, concurrency, timeout, and min-instances settings; verify the rendered service configuration against Singapore. If no-go, record that this deployment was deliberately skipped.
- [ ] 2.2 If deployed, grant the Scheduler identity only the candidate service's invocation permission, verify an unauthenticated request is refused, and manually invoke one authorized cycle; confirm exactly one new observation and updated collector health. If no-go, record why this test was not run.
- [ ] 2.3 Measure candidate-cycle duration and Firestore access against the pre-move baseline; verify the five-minute cadence still has headroom and no new failures occur, or document why cutover was rejected.

## 3. Cut over without dual scheduling

- [ ] 3.1 If the candidate passes, update the existing Scheduler job's URL and OIDC audience to the Taiwan service while retaining the Singapore service for rollback; verify there is exactly one periodic target and the next invocation succeeds. If no-go, verify the Singapore target is unchanged.
- [ ] 3.2 If cut over, observe at least three consecutive scheduled cycles and check health, observation continuity, duplicate/negative intervals, errors, and latency; restore the saved Singapore URI and audience if any acceptance check fails. Record the observed results or the no-go reason.
- [ ] 3.3 Exercise or document the exact rollback commands and expected health checks, verifying the Singapore service and its invocation permission remain available throughout the trial.

## 4. Verify the bill and document the outcome

- [ ] 4.1 After at least 48 hours of reported candidate usage, compare actual Airchive charges and credits by SKU with the settled baseline, including Cloud Run and Firestore cross-region transfer; verify whether the total cost improved and explicitly record any reporting lag. If no cutover occurred, record the baseline and no-go finding instead.
- [ ] 4.2 Update `docs/operations.md` with the actual deployed region, Scheduler target, measured cycle health, dated billing comparison, remaining uncertainty, and rollback procedure; verify it does not promise a zero total bill without a complete billing period.
- [ ] 4.3 After the next complete billing month, check the settled total Airchive bill and record whether it was truly $0; verify the conclusion against all Airchive SKUs and credits, not just the Cloud Run CPU line.
- [ ] 4.4 After a successful trial and explicit operational decision, retire the unused regional service and stale IAM binding, verifying the active Scheduler target and collector health remain correct; otherwise leave the rollback service in place and document why.
- [ ] 4.5 Run `openspec validate evaluate-tier1-cloud-run-region --strict` and verify the change passes validation.
