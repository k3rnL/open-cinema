## Purpose

Defines predictable persistent master and per-endpoint audio level controls whose effects survive route changes and remain understandable when runtime devices are unavailable or read-only.

## ADDED Requirements

### Requirement: Master volume is persistent operational state
The system SHALL maintain one versioned master output level in the inclusive normalized range zero to one and one master mute state independently from graph revisions and temporary route overrides. These values SHALL persist across browser sessions and appliance restarts.

#### Scenario: User changes volume from the dashboard
- **WHEN** an authorized user changes master volume
- **THEN** the new desired value is persisted, reconciled to every active output, and reported together with its observed effective state

#### Scenario: Appliance restarts
- **WHEN** Open Cinema restarts after master volume was set
- **THEN** the persisted value is restored before normal route playback is considered converged

### Requirement: Endpoint level is keyed by logical identity
The system SHALL allow a persistent device-level value and mute state for a logical audio endpoint when its current candidate advertises the corresponding writable capability. Device-level state SHALL be keyed by logical endpoint identity rather than transient PipeWire identifiers, and SHALL remain inspectable while the endpoint is unavailable.

#### Scenario: Headset reconnects with a new runtime identifier
- **WHEN** a known headset returns and resolves to its logical endpoint
- **THEN** its saved device-level state is applied to the new runtime object

#### Scenario: Endpoint is read-only
- **WHEN** an observed endpoint does not advertise writable volume or mute
- **THEN** the Devices page shows the observed value when known and does not offer an enabled mutation control

### Requirement: Effective output level has one explainable calculation
For each active output, the system SHALL derive the effective level from the master level and that logical endpoint's device level, using a neutral default device level when none was saved. Master mute or endpoint mute SHALL silence that output. The API SHALL report desired master state, desired endpoint state, computed effective state, and observed runtime state separately.

#### Scenario: Master and endpoint levels both apply
- **WHEN** master level is 0.8 and an active output's device level is 0.5
- **THEN** the reconciled effective level is 0.4 and the UI can explain both factors

#### Scenario: One of several active outputs is muted
- **WHEN** two outputs are active and only one has endpoint mute enabled
- **THEN** that output is silent while the other continues at its own computed effective level

### Requirement: Volume follows adaptive route changes
The orchestrator SHALL apply effective level and mute state whenever an output becomes active, reconnects, changes runtime identity, or drifts from the desired value. A route SHALL NOT be reported converged until required writable volume state has been applied or a clear degraded reason is recorded.

#### Scenario: Headset replaces main speakers
- **WHEN** routing switches from the main speakers to a connected headset
- **THEN** the headset receives the current master state combined with its own saved device level before the transition is reported converged

#### Scenario: Runtime rejects volume mutation
- **WHEN** a selected output advertised writable volume but applying it fails
- **THEN** playback state is reported degraded with the requested and observed values rather than falsely reporting success

### Requirement: Volume mutations are safe under concurrency and rapid input
Volume writes SHALL use optimistic concurrency or an equivalent monotonic contract. The UI SHALL coalesce rapid slider changes, keep immediate visual feedback, serialize committed writes, and converge on the latest requested value without allowing an older response to replace it.

#### Scenario: User drags the master slider quickly
- **WHEN** many intermediate values are produced in a short interval
- **THEN** the UI remains responsive and the server ultimately persists and applies the last selected value without issuing an unbounded write backlog

#### Scenario: Two clients change master volume
- **WHEN** a client submits against an outdated volume version
- **THEN** the server rejects or rebases the stale write according to the declared contract and neither client silently overwrites newer state

### Requirement: Volume controls communicate scope and state
The dashboard control SHALL be labelled as master volume and the Devices page control SHALL be labelled as device level or input level as applicable. Each control SHALL distinguish desired, applying, effective, read-only, unavailable, and failed states without moving the control during status changes.

#### Scenario: Disconnected output retains a preference
- **WHEN** a logical output has a saved device level but is unavailable
- **THEN** the Devices page shows the saved preference as inactive and explains that it will apply on reconnect

