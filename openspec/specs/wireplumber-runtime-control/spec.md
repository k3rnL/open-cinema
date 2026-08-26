# WirePlumber Runtime Control Specification

## Purpose

Defines WirePlumber through WyrePlumber as Open Cinema's required source of live PipeWire state and runtime control, replacing alternative audio backend implementations and preferences.

## Requirements

### Requirement: WirePlumber is the required audio runtime
The system SHALL require a healthy PipeWire and WirePlumber session for audio orchestration and SHALL expose an explicit unhealthy or unavailable state when it cannot connect.

#### Scenario: Runtime available at startup
- **WHEN** Open Cinema starts and connects to WirePlumber successfully
- **THEN** it obtains a full initial runtime snapshot before reconciling audio graphs

#### Scenario: Runtime unavailable at startup
- **WHEN** Open Cinema cannot connect to WirePlumber
- **THEN** the web/API service remains diagnosable, audio reconciliation is paused, and health reports the connection failure

### Requirement: Audio backend selection is removed
The system SHALL NOT expose selectable PulseAudio, ALSA, or other device-discovery backend preferences and SHALL treat PipeWire/WirePlumber as the single runtime integration.

#### Scenario: Request a removed backend preference route
- **WHEN** a client calls the former audio-backend preference path
- **THEN** no route or compatibility handler exists and runtime health/inventory
  is available only through `/api/audio/v1`

#### Scenario: Device discovery
- **WHEN** the system refreshes its audio inventory
- **THEN** it obtains runtime objects and capabilities from WirePlumber rather than iterating enabled backend plugins

### Requirement: Full runtime snapshots are available
The integration SHALL provide versioned snapshots of relevant devices, nodes, ports, links, metadata, parameters, routes, profiles, defaults, and object properties.

#### Scenario: Inspect live graph
- **WHEN** an authorized client requests the runtime graph
- **THEN** the response contains correlated node, port, and link identities plus relevant properties from one coherent snapshot

### Requirement: Runtime changes are observable
The integration SHALL emit or surface ordered change notifications for object addition, removal, property changes, parameter changes, metadata changes, default changes, and connection lifecycle.

#### Scenario: Headset node appears
- **WHEN** WirePlumber adds the device, route, node, and ports for a headset
- **THEN** Open Cinema updates its inventory and schedules resolution without manual polling by the user

#### Scenario: Event continuity is uncertain
- **WHEN** the connection is interrupted or an event sequence gap is detected
- **THEN** Open Cinema discards unsafe incremental assumptions and obtains a fresh full snapshot

### Requirement: Runtime controls use WirePlumber semantics
The integration SHALL support reading and setting volume and mute, selecting defaults, assigning or clearing stream targets, reading and setting managed metadata, and creating or removing explicitly managed links where policy metadata is insufficient.

#### Scenario: Change output volume
- **WHEN** a user sets volume for an available logical output
- **THEN** the system changes the corresponding writable PipeWire parameter and confirms the observed value

#### Scenario: Move managed stream
- **WHEN** a resolved plan changes a movable stream's target
- **THEN** the system expresses the target through WirePlumber-supported target/default metadata before considering raw links

#### Scenario: Connect an appliance source endpoint directly to a sink endpoint
- **WHEN** a resolved graph connects a source device to a sink device and there is no movable application stream on which target metadata can operate
- **THEN** the system creates only the channel-matched links selected by that graph, labels them with stable Open Cinema ownership and desired-link identities, verifies them through a fresh runtime snapshot, and never claims unrelated links

### Requirement: Managed and unmanaged runtime objects are distinguished
The system SHALL mark resources and mutations it owns with stable Open Cinema identifiers and SHALL avoid deleting or reconfiguring unmanaged objects unless an explicit policy authorizes it.

#### Scenario: External application stream
- **WHEN** an unmanaged application stream appears
- **THEN** Open Cinema observes it and applies only allowed target/default policy without claiming ownership of the stream lifecycle

### Requirement: Runtime identifiers are transient
The system SHALL NOT use PipeWire numeric object identifiers as durable foreign keys in desired graphs or endpoint identity.

#### Scenario: Object serial changes after restart
- **WHEN** PipeWire restarts and recreates managed and physical nodes
- **THEN** logical matching and managed labels restore intent without requiring database identifier migration

### Requirement: Connection access is serialized safely
The integration SHALL support concurrent API reads and reconciliation requests without violating the WirePlumber event-loop and object-lifetime constraints.

#### Scenario: Read during reconciliation
- **WHEN** a client requests runtime status while reconciliation changes metadata or targets
- **THEN** both operations complete against defined snapshot boundaries without unsafe cross-thread object use
