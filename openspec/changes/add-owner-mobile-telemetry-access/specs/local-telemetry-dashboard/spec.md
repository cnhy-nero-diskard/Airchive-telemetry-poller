## MODIFIED Requirements

### Requirement: Dashboard access remains read-only and server-side

All dashboard access to Firestore SHALL execute through the local Python process
using server-side credentials. The browser SHALL NOT receive Google credentials
or direct Firestore client access. This boundary SHALL remain independent of the
separately scoped mobile access defined by `mobile-telemetry-access`.

#### Scenario: User views or filters dashboard data

- **WHEN** the user loads, refreshes, filters, charts, or opens a stored
  observation
- **THEN** the dashboard SHALL perform only Firestore read operations through
  the local Python process
- **AND** dashboard interactions MUST NOT write Firestore data or issue ThinQ
  device operations

#### Scenario: Browser assets are inspected

- **WHEN** dashboard responses and browser-visible state are examined
- **THEN** they MUST NOT contain access tokens, authorization headers, ambient
  credential material, or credential file contents
- **AND** they MUST NOT contain credentials or configuration that lets the
  browser read Firestore directly

#### Scenario: Mobile access is separately enrolled

- **WHEN** the mobile owner read exception is enabled in Firestore rules
- **THEN** the local dashboard SHALL continue to use its existing server-side
  access path
- **AND** that exception SHALL NOT grant the dashboard browser direct access
  beyond the mobile paths and identity defined by `mobile-telemetry-access`
