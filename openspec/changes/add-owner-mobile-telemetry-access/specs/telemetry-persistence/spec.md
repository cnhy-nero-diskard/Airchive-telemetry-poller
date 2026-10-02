## MODIFIED Requirements

### Requirement: Server-side persistence with locked-down client access

Telemetry SHALL be persisted to a dedicated document database project used
exclusively by this collector. Direct client access SHALL remain denied by
default, except for the explicitly enrolled, read-only mobile access defined by
`mobile-telemetry-access`. Direct client writes SHALL remain denied.

#### Scenario: No mobile owner is enrolled

- **WHEN** a direct client requests any Airchive document before owner enrollment
- **THEN** Firestore SHALL deny the request

#### Scenario: An enrolled owner reads mobile history

- **WHEN** the explicitly enrolled owner reads one of the device paths allowed by
  `mobile-telemetry-access`
- **THEN** Firestore SHALL permit only that scoped read
- **AND** every other direct-client read SHALL remain denied

#### Scenario: A mobile client attempts a write

- **WHEN** any direct client attempts to create, update, or delete an Airchive
  document
- **THEN** Firestore SHALL deny the operation, including for the enrolled owner

#### Scenario: The collector authenticates

- **WHEN** the collector reads or writes telemetry
- **THEN** it SHALL do so with server-side administrative credentials obtained
  from the ambient environment
- **AND** a long-lived credential file MUST NOT be bundled with the deployed
  application
