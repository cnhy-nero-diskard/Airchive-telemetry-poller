## ADDED Requirements

### Requirement: Liveness detection is independent of the execution primitive

Detection that the collector has stopped producing observations SHALL rest on evidence the collector itself writes, not on records emitted by whichever execution primitive currently runs it. Changing the execution primitive MUST NOT silently disable the detection.

#### Scenario: The collector stops producing observations

- **WHEN** no successful observation has been recorded for materially longer than the configured cadence
- **THEN** the condition SHALL be detectable from the stored observation series and the collector health record alone
- **AND** detection MUST NOT require the execution runtime's own invocation or execution records

#### Scenario: The execution primitive changes

- **WHEN** the collector is moved to a different execution primitive
- **THEN** liveness detection SHALL continue to function without redefinition
- **AND** any detection that did depend on the retired primitive SHALL be migrated as part of that move rather than left to fail silently

#### Scenario: The collector is running but failing

- **WHEN** the collector is being invoked on schedule but every cycle is failing
- **THEN** the condition SHALL be distinguishable from the collector not being invoked at all
- **AND** both SHALL be reported to the operator

## MODIFIED Requirements

### Requirement: Operational documentation

The change SHALL be accompanied by documentation sufficient for an operator or a future agent to run and understand the system without rediscovering it.

#### Scenario: Documentation is complete

- **WHEN** the change is complete
- **THEN** the documentation SHALL cover project and database creation, local credential setup, API token and client identity setup, device discovery, every environment variable, local execution, deployed execution, the stored data model, the inspection commands, collector health, rate-limit behavior, interval and delta semantics, day-rollover reconciliation, and known device and API limitations

#### Scenario: Findings from discovery are recorded

- **WHEN** discovery and counter validation have been performed against the real device
- **THEN** their findings SHALL be recorded in the documentation, including the confirmed energy property, unit, precision, observed update latency, effective day boundary, and the readable properties this device actually exposes

#### Scenario: The recorded running cost is verified against actual billing

- **WHEN** the documentation states what the deployed collector costs to run
- **THEN** the figure SHALL have been checked against actual billed usage rather than estimated from expected cycle duration alone
- **AND** it SHALL state the billable unit, the allowance it is compared against, and the date the check was performed
- **AND** an estimate that has since been contradicted by billing MUST NOT be left standing in the documentation
