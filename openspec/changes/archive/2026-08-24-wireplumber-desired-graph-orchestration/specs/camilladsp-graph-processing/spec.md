## Purpose

Defines CamillaDSP as a graph processing capability whose validated profile is selected from route intent, signal requirements, and output characteristics rather than managed as a separate competing pipeline system.

## ADDED Requirements

### Requirement: CamillaDSP is an insertable processor rather than an endpoint
The system SHALL expose CamillaDSP in the graph node catalogue as a processing stage with typed inputs and outputs, schema-driven configuration, managed lifecycle, and correlated PipeWire resources.

#### Scenario: Add CamillaDSP to a route
- **WHEN** a user inserts CamillaDSP between an input branch and an output branch
- **THEN** resolution treats it as an audio transformation stage and retains the surrounding endpoints as the route's input and output identities

#### Scenario: CamillaDSP process is not running
- **WHEN** a saved graph contains a CamillaDSP node but no managed instance is ready
- **THEN** the desired node remains editable and resolution exposes its unavailable health, resource requirement, and any permitted bypass

### Requirement: CamillaDSP configurations are reusable processing profiles
The system SHALL represent CamillaDSP device-independent processing intent, filters, mixers, channel mappings, rates, chunks, and output-specific calibration as reusable profiles selectable by desired graphs.

#### Scenario: Reuse living-room profile
- **WHEN** multiple desired graphs reference the living-room processing profile
- **THEN** they reuse one profile definition while retaining graph-specific parameter bindings

### Requirement: CamillaDSP nodes declare signal contracts
A CamillaDSP processing node SHALL declare accepted input descriptors, produced output descriptors, permitted rates and layouts, required endpoint associations, and whether bypass is allowed.

#### Scenario: Select six-channel profile
- **WHEN** the active decoder produces 5.1 PCM and the room output supports six channels
- **THEN** resolution can select a compatible six-channel CamillaDSP profile

### Requirement: Configuration is generated from the resolved plan
The system SHALL generate the concrete CamillaDSP configuration from the selected profile, resolved endpoints, signal descriptor, parameter values, and channel adaptation decisions.

#### Scenario: Headset selected
- **WHEN** output resolution changes from room speakers to a stereo headset
- **THEN** the generated configuration uses the configured headphone profile or explicit bypass rather than retaining room-speaker channel mapping

### Requirement: Configuration is validated before activation
The system SHALL validate generated configuration structurally and through CamillaDSP's validation interface before it becomes eligible for an applied plan.

#### Scenario: Invalid filter parameters
- **WHEN** generated filter or mixer settings are rejected by CamillaDSP
- **THEN** activation is blocked and the resolved plan identifies the profile and validation error

### Requirement: CamillaDSP exposes stable PipeWire-facing endpoints
Managed CamillaDSP instances SHALL expose stable, identifiable input and output nodes or streams that can be matched after process or PipeWire restart.

#### Scenario: CamillaDSP restarts
- **WHEN** the processor restarts and receives new runtime identifiers
- **THEN** reconciliation rematches its managed endpoints and restores the intended route

### Requirement: Reconfiguration is coordinated safely
The processor SHALL participate in ordered mute, configure, verify, route, and unmute transitions when a change can alter sample format, rate, channels, or audible output.

#### Scenario: Channel count changes
- **WHEN** a route changes from six-channel speakers to two-channel headphones
- **THEN** no incompatible audio is intentionally sent during the CamillaDSP reconfiguration window

### Requirement: CamillaDSP health and active profile are observable
The system SHALL expose connection status, engine state, active configuration identity, validation status, input/output descriptors, processing warnings, and last failure.

#### Scenario: WebSocket unavailable
- **WHEN** Open Cinema cannot communicate with CamillaDSP
- **THEN** the processor is unhealthy, affected plans are reevaluated, and diagnostics retain the connection error

### Requirement: Processor resource policy is explicit
The system SHALL allow runtime and graph policy to constrain the number of CamillaDSP instances and define reuse, reconfiguration, or rejection behavior when concurrent graphs request incompatible profiles.

#### Scenario: Single-instance runtime conflict
- **WHEN** two active routes require incompatible CamillaDSP configurations while runtime policy permits one instance
- **THEN** resolution follows declared priority or reports a resource conflict rather than silently replacing one route

### Requirement: Legacy CamillaDSP storage is removed
The system SHALL remove the unused direct CamillaDSP pipeline, mixer, and filter
models and APIs instead of maintaining a competing or compatibility path.

#### Scenario: Install the orchestration schema
- **WHEN** the database migration reaches the desired-graph release
- **THEN** only CamillaDSP profiles and managed processor resources remain
