## ADDED Requirements

### Requirement: Regional cost decisions are recorded from actual billing

Operator documentation SHALL identify the deployed collector and database regions, the billing period examined, relevant charged SKUs and credits, and the observed outcome of any regional cost change. It MUST NOT state that Tier 1 placement guarantees a zero total bill.

#### Scenario: The region change is proposed

- **WHEN** a lower-cost execution region is proposed
- **THEN** the operator SHALL have a documented baseline for total Airchive charges and cycle health in the current region
- **AND** the proposed region and expected new cost categories SHALL be recorded before cutover

#### Scenario: A candidate region has been deployed

- **WHEN** enough billing data has arrived after a regional cutover
- **THEN** the documented comparison SHALL include the actual Cloud Run subtotal and credits, Firestore network charges, and other Airchive SKUs for a stated date range
- **AND** it SHALL say whether the hoped-for zero total bill was observed, not inferred from free-tier quotas alone

#### Scenario: A regional rollback is needed

- **WHEN** the new region must be abandoned
- **THEN** operator guidance SHALL identify the previous service, the Scheduler target and OIDC audience to restore, and the health checks needed to confirm collection resumes
