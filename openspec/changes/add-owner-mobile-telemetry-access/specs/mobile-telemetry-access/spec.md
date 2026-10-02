## Purpose

Allows the enrolled owner of the single monitored air conditioner to read Airchive history from a mobile client while preserving the collector's server-side write boundary.

## ADDED Requirements

### Requirement: Mobile reads require an enrolled owner

Direct Firestore client reads SHALL require a valid Firebase Authentication session whose UID has been explicitly enrolled as the owner of the configured Airchive device. Merely signing in to the Firebase project SHALL NOT grant access. The owner enrollment SHALL be performed through an operator-controlled setup step, not by an unauthenticated or self-authorizing mobile write.

#### Scenario: Enrolled owner reads the configured device
- **WHEN** a signed-in client with the enrolled owner UID requests an allowed document for the configured device
- **THEN** Firestore SHALL permit the read

#### Scenario: Another account or anonymous client reads
- **WHEN** an unauthenticated client or a signed-in client with a different UID requests the same document
- **THEN** Firestore SHALL deny the read

#### Scenario: Signed-in account has not been enrolled
- **WHEN** the owner signs in before the operator completes enrollment
- **THEN** Firestore SHALL deny the read until enrollment is complete

### Requirement: Mobile read scope is limited to required device data

The enrolled owner SHALL be able to read the configured device identity, its telemetry observations, its finalized daily totals, and its collector health document. Direct client access to another device, metadata profiles, reconciliation runtime records, and every other Firestore path SHALL remain denied. Reads of an allowed observation or daily-total document include that entire document, including its raw provider response; access SHALL NOT be described as field-limited.

#### Scenario: Owner reads supported history
- **WHEN** the enrolled owner reads `devices/{deviceId}`, `devices/{deviceId}/telemetry/{sampleId}`, `devices/{deviceId}/dailyTotals/{localDate}`, or `devices/{deviceId}/runtime/collector` for the configured device
- **THEN** Firestore SHALL permit the read

#### Scenario: Owner requests another path
- **WHEN** the enrolled owner requests an unlisted path or a different device ID
- **THEN** Firestore SHALL deny the read

#### Scenario: Owner lists telemetry or daily totals
- **WHEN** the enrolled owner requests a bounded page of telemetry or daily-total documents for the configured device
- **THEN** Firestore SHALL permit the list query
- **AND** a query without the required page bound SHALL be denied

### Requirement: Mobile clients cannot mutate collector data

All direct client create, update, and delete operations SHALL remain denied, including operations attempted by the enrolled owner. The collector and local inspection tools SHALL continue to use their existing server-side credentials independently of mobile security rules.

#### Scenario: Owner attempts a write
- **WHEN** the enrolled owner attempts to create, update, or delete a document on any Airchive path
- **THEN** Firestore SHALL deny the operation

#### Scenario: Scheduled collection continues
- **WHEN** the collector writes an observation using its server identity after mobile rules are deployed
- **THEN** the write SHALL continue to succeed without a mobile session

### Requirement: Mobile history exposes stable synchronization markers

Allowed telemetry reads SHALL retain `observedAt`, `persistedAt`, `reconciledAt` when present, `sampleId`, energy values and units, and quality fields needed for a client to build a local projection. Finalized daily totals SHALL remain readable by local date. The documented client contract SHALL distinguish a stored observation from live ThinQ device state and SHALL preserve null intervals and quality flags rather than interpreting them as zero consumption.

#### Scenario: Client catches up after a pause
- **WHEN** an authorized client resumes after new observations, completeness upgrades, or rollover reconciliation
- **THEN** it SHALL be able to query allowed telemetry by `persistedAt` and `reconciledAt` and fetch bounded result pages

#### Scenario: Client displays historical energy
- **WHEN** an observation has a null interval value or non-normal quality status
- **THEN** the documented read contract SHALL identify it as missing, incomplete, or anomalous data rather than measured zero

### Requirement: Owner setup and revocation are documented

Operator documentation SHALL explain Firebase app registration, authentication setup, owner UID enrollment, supported read paths, the distinction between Firebase sign-in and the separate LG ThinQ token, and how to revoke mobile reads. It SHALL state that service-account credentials MUST NOT be installed on a phone.

#### Scenario: Owner configures a fresh app install
- **WHEN** the operator follows the setup instructions and the owner signs in from the app
- **THEN** the owner SHALL be able to read the allowed paths after explicit enrollment without changing collector credentials

#### Scenario: Mobile access is revoked
- **WHEN** the operator removes the owner's authorization and deploys the changed rules
- **THEN** subsequent server-backed client reads SHALL be denied
