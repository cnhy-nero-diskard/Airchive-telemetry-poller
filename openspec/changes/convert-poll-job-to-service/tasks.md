## 1. HTTP entry point

- [x] 1.1 Add `src/airchive/serve.py` exposing a stdlib `http.server` handler that accepts POST on a single path, calls `poll_cmd.run(once=True)`, and maps exit code 0 to 200 and non-zero to 500; verify by starting it locally and confirming both codes with a forced-failure stub
- [x] 1.2 Bind to `0.0.0.0` on the port given by `$PORT`, defaulting to 8080; verify `PORT=9099 airchive serve` listens on 9099
- [x] 1.3 Reject any method other than POST and any path other than the trigger path with 404/405 and no cycle run; verify with a test asserting `poll_cmd.run` is never called
- [x] 1.4 Add an `airchive serve` subcommand to `cli.py` alongside `poll`, leaving `poll --once` untouched; verify `airchive poll --once` still runs a single cycle locally
- [x] 1.5 Ensure a cycle raising an unexpected exception returns 500 rather than killing the process, and logs through the existing structured logger with no secrets; verify with a test that forces an exception and asserts the server still serves the next request

## 2. Container

- [x] 2.1 Change the `Dockerfile` `CMD` to `["serve"]`, keeping `ENTRYPOINT ["airchive"]` so `poll --once` remains reachable by overriding the command; verify `docker run --entrypoint airchive <image> poll --once` still works
- [x] 2.2 Update the Dockerfile's "One cycle per invocation" comment to describe request-triggered invocation; verify the comment matches actual behavior
- [x] 2.3 Build and push the image as `collector:0.2.0` to the existing Artifact Registry repo; verify the tag is listed by `gcloud artifacts docker images list`
- [x] 2.4 Confirm the new image still runs correctly as the existing job before any cutover; verify by executing the job once against `0.2.0` with the command overridden to `poll --once` and checking a normal observation lands

## 3. Service deployment

- [x] 3.1 Deploy Cloud Run service `airchive-poll-svc` in `asia-southeast1` from `collector:0.2.0` with 0.5 vCPU, 512Mi, concurrency 1, min instances 0, `--no-allow-unauthenticated`, running as the existing collector service account; verify `gcloud run services describe` reports those values
- [x] 3.2 Attach the `lg-thinq-pat` secret as `LG_THINQ_PAT` and set the same environment variables the job carries; verify by comparing the rendered env of job and service
- [x] 3.3 Set the service request timeout to 120s — well under the 300s cadence — so a hung cycle cannot overlap the next slot; verify the configured timeout
- [x] 3.4 Grant `roles/run.invoker` on the service to `airchive-scheduler@…` only; verify `gcloud run services get-iam-policy` lists that one binding and no `allUsers`
- [x] 3.5 Confirm the service refuses an unauthenticated request; verify a plain `curl` to the URL returns 403

## 4. Cutover

- [x] 4.1 Invoke the service once manually with an OIDC token; verify a new observation appears in Firestore with `NORMAL` status and the health record's last-success time advances
- [x] 4.2 Retarget `airchive-poll-5min` to the service URL with an OIDC token and the service URL as audience, leaving the job deployed but untriggered; verify the scheduler's next run succeeds
- [x] 4.3 Observe three consecutive scheduled cycles; verify no negative interval appears and at most one `COARSE_INTERVAL` spans the cutover
- [x] 4.4 Record measured request durations across those cycles; verify against the ~22 s modelled in design.md D4 and note the variance

## 5. Liveness detection

- [x] 5.1 Re-key the "no completed cycle for 30 minutes" signal onto collector health and observation recency rather than Cloud Run Job execution records; verify it still fires by simulating a stalled collector
- [x] 5.2 Confirm the signal distinguishes "not being invoked" from "invoked but every cycle failing"; verify both conditions produce a distinct, reportable state
- [x] 5.3 Complete this group before task 6.1 — deleting the job first would silently disable the alert

## 6. Retire the job

- [x] 6.1 Delete the `airchive-poll` job; verify `gcloud run jobs list` no longer lists it
- [x] 6.2 Revoke the scheduler identity's `run.invoker` on the deleted job if any binding survives; verify the scheduler retains that role only on the service
- [x] 6.3 Add an Artifact Registry cleanup policy removing untagged images; verify the four current untagged versions are collected and repo size drops

## 7. Cost verification

- [x] 7.1 After 48 hours on the service, read actual billed Cloud Run usage from the billing console grouped by SKU; verify the instance-based CPU SKU no longer appears
- [x] 7.2 Compute realised vCPU-seconds/month from measured durations and compare against the 180,000 request-based allowance, including backlogium's ~18,000; verify total draw is under 60%
- [x] 7.3 Decide from measured data whether to drop to 0.25 vCPU per design.md D4; verify the decision and its basis are written down either way
- [x] 7.4 Create a billing budget alert on the billing account at a $1 threshold; verify an alert exists and names a notification target

## 8. Documentation

- [x] 8.1 Replace the falsified cost check in `docs/operations.md` ("8,640 executions/month × ~5 s ≈ 43k vCPU-seconds against a 180k free tier") with the verified figure from task 7.1, stating billable unit, allowance, and date checked
- [x] 8.2 Update the deployment topology table so the cost row reflects billing granularity, and record why a request-billed service preserves — rather than reverses — the original job-over-always-on-service decision
- [x] 8.3 Update the "What is actually deployed" table: service instead of job, new image tag, CPU, concurrency, min instances, and the OIDC trigger
- [x] 8.4 Update the collector-health section to describe the re-keyed liveness signal; verify it no longer references job executions
- [x] 8.5 Run `openspec validate --change convert-poll-job-to-service --strict`; verify it passes

## 9. Spec baseline

- [x] 9.1 Before archiving this change, sync `add-lg-aircon-telemetry-poller` into `openspec/specs/` so the `MODIFIED` deltas here have a base to merge into; verify `openspec/specs/collector-runtime/spec.md` and `collector-operations/spec.md` exist and contain the requirements this change modifies
