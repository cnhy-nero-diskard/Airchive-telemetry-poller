## Purpose

Provides a local, read-only visual interface for understanding Airchive telemetry and collector health without exposing Firestore directly to a browser or repeatedly reading unchanged history.

## ADDED Requirements

### Requirement: Dashboard runs as a local inspection surface

The system SHALL provide a command that starts the telemetry dashboard on the operator's machine. The dashboard SHALL bind to a loopback address by default and SHALL use the existing inspection configuration and ambient Google credentials without requiring ThinQ credentials.

#### Scenario: Operator starts the dashboard
- **WHEN** the operator invokes the dashboard command with valid `FIREBASE_PROJECT_ID` and `LG_DEVICE_ID` configuration
- **THEN** the system SHALL start the dashboard on a loopback URL
- **AND** it SHALL display the configured device's stored data

#### Scenario: Inspection configuration is invalid
- **WHEN** required Firestore inspection configuration is absent or invalid
- **THEN** the dashboard SHALL present an actionable configuration error without starting data synchronization
- **AND** it MUST NOT reveal credential values

### Requirement: Dashboard access remains read-only and server-side

All dashboard access to Firestore SHALL execute through the local Python process using server-side credentials. The browser SHALL NOT receive Google credentials or direct Firestore access, and dashboard interactions MUST NOT write Firestore data or issue ThinQ device operations.

#### Scenario: User views and filters telemetry
- **WHEN** the user loads, refreshes, filters, charts, or opens a stored observation
- **THEN** the dashboard SHALL perform only Firestore read operations
- **AND** the existing deny-all client rules SHALL remain sufficient

#### Scenario: Browser assets are inspected
- **WHEN** dashboard responses and browser-visible state are examined
- **THEN** they MUST NOT contain access tokens, authorization headers, ambient credential material, or credential file contents

### Requirement: Overview communicates current collector state

The dashboard SHALL summarize the collector health record and most recent stored observation, including last attempt, last success, age of the latest observation, consecutive failures, pending reconciliations, raw daily energy value and unit, most recent interval value and duration, interval status, source outcomes, and available principal device state.

The dashboard SHALL prioritize the most useful health and energy answers, use plain-language labels, and keep technical diagnostics behind clearly named secondary controls. It SHALL provide a visible legend for quality states and concise hints for ranges, coverage, refreshing, observation inspection, and raw payload loading.

#### Scenario: Current data is healthy
- **WHEN** a recent successful observation and healthy collector record exist
- **THEN** the overview SHALL present their values and healthy status without requiring the user to inspect raw documents

#### Scenario: Collection is stale or failing
- **WHEN** the latest observation is older than the expected cadence or the health record reports failures
- **THEN** the overview SHALL make the stale or failing condition visually distinct
- **AND** it SHALL show the relevant stored failure class and safe message when available

#### Scenario: A field is unavailable
- **WHEN** an observation lacks an energy, state, health, or reconciliation field
- **THEN** the dashboard SHALL show that value as unavailable rather than inventing a default

#### Scenario: Operator is unfamiliar with telemetry terminology
- **WHEN** the operator opens the dashboard without prior knowledge of its status model
- **THEN** the page SHALL identify a clear starting point and group related information by purpose
- **AND** it SHALL explain normal, anomalous, missing, stale, and incomplete states without relying on color alone
- **AND** it SHALL provide actionable hints beside the controls they describe

### Requirement: Telemetry is visualized without weakening quality semantics

The dashboard SHALL let the user select a bounded time range and view interval consumption over time in the stored local timezone. It SHALL preserve null intervals, interval statuses, quality flags, and source failures so incomplete data is not presented as measured zero consumption.

#### Scenario: User views a time range
- **WHEN** the user selects a supported time range
- **THEN** the dashboard SHALL chart observations in chronological order using `energy.intervalValueNumber`
- **AND** it SHALL identify gaps or non-normal observations instead of joining them as ordinary measurements

#### Scenario: Dashboard summarizes consumption
- **WHEN** the dashboard displays a consumption total for the selected range
- **THEN** it SHALL sum only stored non-null interval values
- **AND** it SHALL display coverage or incompleteness alongside the total whenever expected intervals are absent, unresolved, or unusable

#### Scenario: Timezone is displayed
- **WHEN** observation times or range boundaries are rendered
- **THEN** the dashboard SHALL render them in the configured day timezone
- **AND** it SHALL label that timezone visibly

### Requirement: Observations and anomalies are inspectable

The dashboard SHALL provide a reverse-chronological observation table, anomaly-focused filtering, and a detail view for a selected sample. Summary views SHALL expose normalized energy, quality, source, and principal state fields; bulky raw payloads SHALL be retrieved only when the user explicitly requests them.

#### Scenario: User filters recent observations
- **WHEN** the user changes the time range or selects anomaly-only filtering
- **THEN** the table SHALL update from the available data
- **AND** anomaly filtering SHALL use the same status and flag definitions as the existing inspection command

#### Scenario: User opens observation details
- **WHEN** the user selects a sample
- **THEN** the dashboard SHALL show its normalized stored fields and storage identity
- **AND** it SHALL offer an explicit action to load its raw payload

#### Scenario: User does not request raw data
- **WHEN** the user browses overview, charts, and tables without opening raw details
- **THEN** raw energy and state payloads SHALL NOT be fetched or persisted by the dashboard cache

### Requirement: Local cache minimizes repeated Firestore reads

The dashboard SHALL maintain a persistent, user-local cache of the normalized projection needed by its overview, charts, and tables. It SHALL reuse already-covered ranges and incrementally synchronize new, upgraded, and reconciled observations without treating cached data as the source of truth.

#### Scenario: A range is loaded for the first time
- **WHEN** the selected range is not covered by the local cache
- **THEN** the dashboard SHALL read only the missing bounded range from Firestore
- **AND** it SHALL persist the normalized results and completed coverage marker atomically

#### Scenario: A covered range is revisited
- **WHEN** the user selects a range already covered by the cache
- **THEN** the dashboard SHALL render cached observations without rereading the full range
- **AND** it SHALL perform only the incremental revalidation needed to discover later changes

#### Scenario: Stored observations change after caching
- **WHEN** Firestore contains a newly persisted, completeness-upgraded, or reconciled observation after the last successful synchronization
- **THEN** the next refresh SHALL upsert that observation into the local cache
- **AND** it SHALL preserve the Firestore version as authoritative

#### Scenario: Cache synchronization fails partway
- **WHEN** any required Firestore query fails during synchronization
- **THEN** the dashboard MUST NOT advance the successful synchronization watermark or mark an incomplete range as covered
- **AND** it SHALL retain the last valid cached data for a later retry

### Requirement: Refresh and cache recovery are explicit

The dashboard SHALL refresh no faster than the collector cadence by default, SHALL provide a manual refresh action, and SHALL expose the age of its last successful Firestore synchronization. It SHALL allow the local cache to be cleared and rebuilt without affecting Firestore.

#### Scenario: Automatic refresh runs
- **WHEN** the dashboard remains open across a collector interval
- **THEN** it SHALL perform an incremental synchronization rather than reload all visible history

#### Scenario: Firestore is temporarily unavailable
- **WHEN** synchronization fails but cached data exists
- **THEN** the dashboard SHALL continue displaying the cached data with a stale warning and the failed refresh time

#### Scenario: Cache is absent or corrupt
- **WHEN** the local cache cannot be opened or validated
- **THEN** the dashboard SHALL offer or perform a safe local rebuild
- **AND** it MUST NOT modify Firestore as part of recovery

#### Scenario: Operator clears the cache
- **WHEN** the operator confirms a cache reset
- **THEN** only the local dashboard cache SHALL be removed or recreated
- **AND** the next view SHALL repopulate it from Firestore as needed
