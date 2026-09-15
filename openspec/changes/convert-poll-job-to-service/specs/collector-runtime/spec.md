## ADDED Requirements

### Requirement: The collector is invocable through an authenticated request interface

The collector SHALL expose a request-triggered entry point that performs exactly one observation cycle per accepted request. The interface exists so that the scheduling mechanism and the execution runtime can be chosen independently of one another; it MUST NOT become a control surface for the device.

#### Scenario: An authorized request runs one cycle

- **WHEN** an authorized caller issues a request to the collector's entry point
- **THEN** exactly one observation cycle SHALL be performed
- **AND** the response SHALL report whether the cycle succeeded or failed
- **AND** no additional cycle SHALL be started as a side effect of that request

#### Scenario: An unauthenticated request is refused

- **WHEN** a request arrives without valid proof of an authorized caller identity
- **THEN** the collector SHALL refuse it
- **AND** no observation cycle SHALL be performed
- **AND** no device API call SHALL be issued

#### Scenario: Concurrent requests do not overlap cycles

- **WHEN** a request arrives while a cycle triggered by an earlier request is still in progress
- **THEN** the cycles MUST NOT interleave within a single execution context
- **AND** the existing protection against a cycle overrunning its interval SHALL continue to apply

#### Scenario: The entry point holds no state between requests

- **WHEN** consecutive cycles are triggered by separate requests
- **THEN** each cycle SHALL reconstruct the state it needs from persisted storage and the current API responses
- **AND** correctness MUST NOT depend on the two requests reaching the same execution instance

#### Scenario: The interface exposes nothing beyond triggering a cycle

- **WHEN** the request interface is reachable
- **THEN** it SHALL offer no operation that reads back stored telemetry, alters stored telemetry, or sends any command to the device

## MODIFIED Requirements

### Requirement: Deployment topology is chosen against stated criteria

The execution environment SHALL be selected by evaluating the cadence against cost, **billing granularity**, reliability, credential handling, restart behavior, observability, and API rate limits. An always-running process MUST NOT be adopted merely because the workload involves polling.

Billing granularity means the runtime's minimum billable unit per invocation. Where that unit exceeds the duration of a cycle, the evaluation SHALL use the billable unit rather than the expected cycle duration, because the difference is charged.

#### Scenario: The topology is decided

- **WHEN** the deployment approach is chosen
- **THEN** the evaluation of the considered options against each stated criterion SHALL be recorded
- **AND** the chosen option SHALL be the simplest one that satisfies them

#### Scenario: The recorded cost basis is stated in billable units

- **WHEN** the cost criterion is evaluated for a candidate topology
- **THEN** the recorded figure SHALL be derived from the runtime's minimum billable unit, the observed cycle duration, and the allocated resources
- **AND** it SHALL name the free allowance it is being compared against
- **AND** where an allowance is shared across more than one deployed workload, the recorded figure SHALL account for the other workloads drawing on it

#### Scenario: A recorded cost basis is contradicted by actual billing

- **WHEN** actual billed usage for the deployed collector diverges materially from the recorded cost basis
- **THEN** the recorded basis SHALL be corrected against the observed billing
- **AND** the topology SHALL be re-evaluated against the corrected figure rather than the original estimate

#### Scenario: Deployed credentials are ambient

- **WHEN** the collector runs in the deployed environment
- **THEN** it SHALL obtain database credentials from the runtime's attached identity
- **AND** a credential file MUST NOT be shipped in the deployment artifact
- **AND** the API token SHALL be supplied from a managed secret store rather than embedded in the artifact or in plain configuration

#### Scenario: The triggering identity is separate from the collecting identity

- **WHEN** an external scheduler triggers the collector
- **THEN** the identity permitted to trigger it SHALL hold only the permission required to invoke it
- **AND** the identity under which the collector runs SHALL NOT hold that triggering permission
- **AND** the collecting identity SHALL retain only the permission required to write telemetry

#### Scenario: Event-driven subscription is not required

- **WHEN** the initial collector is delivered
- **THEN** it SHALL rely on periodic sampling only
- **AND** event or message-based subscription SHALL NOT be a prerequisite for delivery
- **AND** any benefit it might offer for finer state-change resolution SHALL be recorded as a future enhancement
