# Audio Endpoint Inventory Specification

## Purpose

Defines durable logical audio endpoints and their relationship to transient PipeWire devices, nodes, ports, routes, profiles, and capabilities observed through WirePlumber.

## Requirements

### Requirement: Logical endpoints have stable identity
The system SHALL represent user-facing inputs and outputs as logical endpoints with stable application identity, labels, tags, direction, and matching criteria rather than PipeWire numeric identifiers.

#### Scenario: Physical device reconnects
- **WHEN** a physical device disconnects and later returns with new runtime object identifiers
- **THEN** it is matched to the same logical endpoint when its stable properties satisfy that endpoint's selector

### Requirement: Endpoint selectors use observable properties
The system SHALL allow endpoint selectors to match documented device, node, route, profile, media-class, direction, and custom properties using exact, set, and pattern predicates.

#### Scenario: Match main speakers
- **WHEN** an Audio/Sink node has the configured device serial and route name
- **THEN** the endpoint selector identifies it as the configured main-speaker endpoint

#### Scenario: Missing required property
- **WHEN** an observed object lacks a property required by a selector
- **THEN** that object does not match and the reason is available in endpoint diagnostics

### Requirement: Endpoint matching is deterministic and explainable
The system SHALL resolve selector matches deterministically and SHALL report ambiguous matches instead of silently choosing an arbitrary object.

#### Scenario: Unique match
- **WHEN** exactly one eligible observed endpoint satisfies all selector predicates
- **THEN** the logical endpoint binds to it and records the matching evidence

#### Scenario: Ambiguous match
- **WHEN** multiple equally eligible observed endpoints satisfy the selector
- **THEN** the logical endpoint is marked ambiguous until a stronger selector or explicit binding resolves it

### Requirement: Inventory distinguishes availability states
The system SHALL distinguish at least discovered, route-available, selected, linked, active-signal, suspended, unavailable, and error states where the underlying runtime exposes them.

#### Scenario: Bluetooth device connected but idle
- **WHEN** a Bluetooth endpoint exists and has an available route but no active stream
- **THEN** conditions may distinguish it from an endpoint that is actively carrying a signal

#### Scenario: Device remains known while absent
- **WHEN** an endpoint is not present in the latest runtime snapshot
- **THEN** it remains in the logical inventory as unavailable with its last-seen information

### Requirement: Inventory exposes capabilities
The system SHALL expose available formats, rates, channel counts, channel positions, profiles, routes, volume, mute, port directions, and relevant latency information when supplied by PipeWire.

#### Scenario: Multichannel sink is observed
- **WHEN** a sink advertises stereo and multichannel formats
- **THEN** its inventory representation includes each advertised capability needed for route planning

#### Scenario: Capability is unknown
- **WHEN** the runtime does not provide a capability value
- **THEN** the inventory marks that value unknown rather than inventing a default

### Requirement: Inventory distinguishes endpoint candidates from processor resources
The system SHALL classify managed processor nodes and ports separately from physical or external endpoint candidates, even though both are observed through WirePlumber.

#### Scenario: CamillaDSP ports are observed
- **WHEN** a managed CamillaDSP instance exposes PipeWire input and output nodes
- **THEN** inventory diagnostics correlate them to the processor instance and do not propose them as a physical input or output binding

#### Scenario: Processor output is intentionally exposed
- **WHEN** a graph node type explicitly declares a processor port as a public reusable interface
- **THEN** it is selectable through that graph or subgraph interface rather than being mistaken for newly discovered hardware

### Requirement: Users can explicitly bind endpoints
The system SHALL allow an authorized user to bind a logical endpoint to an observed device or node and SHALL derive a reviewable selector from stable available properties.

#### Scenario: Bind an ambiguous headset
- **WHEN** a user selects one of multiple matching headsets
- **THEN** the system proposes and stores selector criteria that distinguish the chosen endpoint

### Requirement: Endpoint groups support intent
The system SHALL allow logical endpoints to be grouped and tagged for selectors such as preferred outputs, headsets, room speakers, TV inputs, and Bluetooth programme sources.

#### Scenario: Preferred-output group
- **WHEN** a rule targets the preferred-output group
- **THEN** resolution considers only available endpoints in that group according to the rule's ordering

### Requirement: Runtime inventory updates are monotonic per snapshot version
The system SHALL version observed runtime snapshots and SHALL not apply an older observation after a newer snapshot has been accepted.

#### Scenario: Delayed event arrives
- **WHEN** an event associated with an older runtime generation arrives after a full newer snapshot
- **THEN** the inventory ignores or reconciles it without reverting newer endpoint state
