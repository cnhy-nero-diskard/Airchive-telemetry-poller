## Why

The request-billed collector in Singapore (`asia-southeast1`, Cloud Run Tier 2) produced a $0.047062 Cloud Run subtotal over the 2026-09-16 through 2026-09-21 billing report despite projected usage well below the shared request-based free allowance. The operator wants to evaluate a Tier 1 region for an optimistically zero monthly bill, without assuming that a region change will make every charge disappear.

## What Changes

- Check the billing account's actual free-tier credit allocation and all Airchive SKUs before attributing the residual charge to Tier 2 pricing.
- Evaluate moving only `airchive-poll-svc` to a Tier 1 region, with `asia-east1` (Taiwan) as the initial candidate; retain the existing Singapore Firestore database and five-minute cadence.
- Compare predicted and measured total cost, including Cloud Run, Firestore cross-region transfer, Scheduler, Artifact Registry, and any other billed SKUs, along with cycle latency and reliability.
- If the evidence supports migration, cut over the private OIDC Scheduler target safely, verify collector continuity, and preserve a tested rollback to the Singapore service.
- Record actual post-move billing and the conclusion in operator documentation. Zero cost is an objective to verify, not an acceptance assumption.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `collector-runtime`: Regional deployment decisions must consider total billed cost, data locality, latency, and rollback instead of comparing Cloud Run CPU tiers alone.
- `collector-operations`: Operator documentation must show the deployed region and verified, dated billing evidence without promising a zero bill from free-tier estimates.

## Impact

- **Cloud resources:** Potential new Cloud Run service in `asia-east1`, Scheduler URL/OIDC audience and IAM changes, with Singapore service retained until the cutover is proven.
- **Data:** The existing default Firestore database remains in `asia-southeast1`; no database relocation, duplicate database, or telemetry schema change is included.
- **Code/docs:** Deployment configuration and `docs/operations.md` may change; collector behavior and data model do not.
- **Risk:** Cross-region Firestore traffic and latency, billing-account-wide free-tier allocation, and cutover/rollback errors could offset savings. A zero bill is not guaranteed.
