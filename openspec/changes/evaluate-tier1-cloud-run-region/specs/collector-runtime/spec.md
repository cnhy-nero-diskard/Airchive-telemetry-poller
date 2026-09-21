## ADDED Requirements

### Requirement: Regional deployment is justified by end-to-end evidence

A change to the collector's execution region SHALL be evaluated against total operating cost, database locality, cycle latency, reliability, and the existing five-minute cadence. A lower Cloud Run price tier alone MUST NOT be treated as proof of a zero bill.

#### Scenario: A Tier 1 region is considered

- **WHEN** an operator evaluates a Tier 1 Cloud Run location
- **THEN** the comparison SHALL include the existing region, the candidate region, and the actual location of the telemetry database
- **AND** it SHALL account for Cloud Run charges and credits, cross-region data transfer, and other affected billed services
- **AND** a predicted zero bill SHALL be labeled as an estimate until supported by billing evidence

#### Scenario: The collector runs in a different region from its database

- **WHEN** the execution service is moved while the telemetry database remains in its original location
- **THEN** observations and health records SHALL continue to be written to the existing database without changing their schema or semantics
- **AND** cycle duration and failures SHALL be checked against the pre-move baseline and the five-minute cadence

#### Scenario: Regional cutover fails

- **WHEN** the candidate service cannot complete scheduled cycles or causes unacceptable latency, failures, or cost
- **THEN** the operator SHALL be able to restore the prior region's service as the sole scheduled target without losing the persisted observation series
- **AND** the failed candidate SHALL NOT continue receiving scheduled invocations
