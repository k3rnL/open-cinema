## MODIFIED Requirements

### Requirement: Inventory exposes capabilities
The system SHALL expose available formats, rates, channel counts, channel positions, profiles, routes, volume, mute, port directions, relevant latency information, and whether each operational value is readable or writable when supplied by PipeWire.

#### Scenario: Multichannel sink is observed
- **WHEN** a sink advertises stereo and multichannel formats
- **THEN** its inventory representation includes each advertised capability needed for route planning

#### Scenario: Writable volume is observed
- **WHEN** the runtime reports a volume property and grants mutation for an endpoint candidate
- **THEN** the inventory identifies both the current value and that volume is writable

#### Scenario: Capability is unknown
- **WHEN** the runtime does not provide a capability value
- **THEN** the inventory marks that value unknown rather than inventing a default or writable control

### Requirement: Inventory distinguishes endpoint candidates from processor resources
The system SHALL classify managed processor nodes, adapter processes, and their PipeWire ports separately from physical or external endpoint candidates. The end-user Devices inventory SHALL contain logical endpoints and their observed device candidates, while supervised software SHALL be discoverable through a dedicated managed-resource inventory.

#### Scenario: CamillaDSP ports are observed
- **WHEN** a managed CamillaDSP instance exposes PipeWire input and output nodes
- **THEN** runtime diagnostics correlate them to the processor instance, Devices does not propose them as a physical binding, and Managed resources reports the instance

#### Scenario: Processor output is intentionally exposed
- **WHEN** a graph node type explicitly declares a processor port as a public reusable interface
- **THEN** it is selectable through that graph or subgraph interface rather than being mistaken for newly discovered hardware

#### Scenario: Managed ROC adapter exposes an endpoint
- **WHEN** a supervised ROC adapter creates an externally meaningful audio input or output
- **THEN** Managed resources contains the adapter lifecycle while Devices may contain its correlated endpoint candidate without duplicating the adapter process as a device

## ADDED Requirements

### Requirement: Endpoint controls resolve through logical identity
An authorized mutation requested for a logical endpoint SHALL resolve its current unique runtime candidate immediately before execution and SHALL reject unavailable, ambiguous, stale, or read-only targets without persisting a transient PipeWire identifier as endpoint identity.

#### Scenario: User changes a connected output level
- **WHEN** a logical output uniquely resolves to a current writable candidate
- **THEN** the system applies the requested endpoint state to that candidate and returns refreshed desired and observed state

#### Scenario: Candidate changed before mutation
- **WHEN** the submitted observation version is older than the endpoint's current runtime resolution
- **THEN** the system rejects the stale mutation and asks the client to refresh instead of controlling the former runtime object

#### Scenario: Unrelated runtime observation advances
- **WHEN** the selected endpoint candidate keeps the same runtime generation and node identity while another runtime observation advances
- **THEN** the existing endpoint control token remains valid and the mutation is not rejected as stale
