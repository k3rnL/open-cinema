# CamillaDSP Graph Processing Specification

## Purpose

TBD: Describe CamillaDSP processing within managed audio graphs and destination routing after archive.

## Requirements

### Requirement: CamillaDSP uses native PipeWire processing nodes
Managed CamillaDSP version 4 or later instances SHALL use native PipeWire capture and playback nodes with stable per-instance names and groups and with backend autoconnect disabled.

#### Scenario: Instance becomes ready
- **WHEN** Open Cinema starts a prepared CamillaDSP instance
- **THEN** the instance publishes one matchable native capture node and one matchable native playback node for WirePlumber-managed linking

### Requirement: Destination profile is independent from transient content layout
The default CamillaDSP profile SHALL be selected from desired route intent, output association, parameters, and compatible working contract rather than from programme channel count alone.

#### Scenario: Stereo menu on room speakers
- **WHEN** a room-speaker route changes from a 5.1 movie to a stereo menu without an explicit content-dependent rule
- **THEN** the room CamillaDSP profile and native node contracts remain active

#### Scenario: Explicit content rule
- **WHEN** a graph rule explicitly selects a different processing profile for a stable observed content format
- **THEN** resolution may select and safely activate that profile with an explanation identifying the rule and observation

### Requirement: CamillaDSP accepts a stable working bus
The system SHALL support CamillaDSP profiles whose capture channel layout is a stable working bus while playback channels and explicit mixers represent the selected destination.

#### Scenario: Stereo carried on a seven-one working bus
- **WHEN** only front-left and front-right programme channels are active on an eight-channel room bus
- **THEN** the unchanged CamillaDSP configuration processes those channels and treats inactive channels as silence

#### Scenario: Seven-one input to five-one speakers
- **WHEN** an eight-channel working bus targets a six-channel speaker profile
- **THEN** a declared CamillaDSP mixer performs the 8-to-6 adaptation rather than the decoder silently dropping channels

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
Managed CamillaDSP instances SHALL expose stable, identifiable input and output nodes or streams whose complete declared port sets can be matched after process or PipeWire restart. A node match without all ports required by the selected profile SHALL NOT satisfy route readiness.

#### Scenario: CamillaDSP restarts
- **WHEN** the processor restarts and receives new runtime identifiers
- **THEN** reconciliation rematches its managed endpoints and all profile-required ports before restoring the intended route

#### Scenario: CamillaDSP node appears before all declared ports
- **WHEN** a managed CamillaDSP node is observed but one or more channels required by its active profile are absent
- **THEN** the instance remains waiting for runtime resources and programme ingress is not connected to it

### Requirement: Reconfiguration is coordinated safely
The processor SHALL participate in ordered suppress, configure, resource-readiness, downstream-route, topology-verification, ingress-activation, final-verification, and recovery behavior when a change can alter sample format, rate, channels, runtime identities, or audible output.

#### Scenario: Channel count changes
- **WHEN** a route changes from six-channel speakers to two-channel headphones
- **THEN** no incompatible audio is intentionally sent during the CamillaDSP reconfiguration window

#### Scenario: Eight-channel route is restored after restart
- **WHEN** CamillaDSP restarts while an eight-channel profile remains selected
- **THEN** all required output and input channels are linked and freshly verified before the source-facing link activates processing, and a partial route is never reported converged

#### Scenario: Topology verification fails
- **WHEN** CamillaDSP is process-healthy but its required PipeWire links do not converge before timeout
- **THEN** its affected route remains safely suppressed, the applied plan is not advanced, and diagnostics distinguish topology failure from processor control health

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
