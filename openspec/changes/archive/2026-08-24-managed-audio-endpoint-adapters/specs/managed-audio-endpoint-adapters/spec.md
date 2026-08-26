## Purpose

Defines persistent, user-managed resources that create stable PipeWire-facing audio endpoints for network transport and repeatable file-based debugging without requiring manual shell commands.

## ADDED Requirements

### Requirement: Endpoint adapters are persistent desired resources
The system SHALL persist each managed endpoint adapter with a stable identity, user-facing name, adapter type, typed configuration, enabled state, and optimistic-concurrency version independently from its transient process and PipeWire object identifiers.

#### Scenario: Runtime restarts
- **WHEN** PipeWire, WirePlumber, or the Open Cinema orchestrator restarts
- **THEN** every enabled valid adapter is recreated from persistent configuration with the same application identity

#### Scenario: Adapter is disabled
- **WHEN** a user disables an adapter
- **THEN** its configuration remains saved while its managed process and PipeWire endpoint are removed

### Requirement: Adapter types have schema-driven configuration
Each supported adapter type SHALL publish a versioned configuration schema, direction, display metadata, defaults, and validation constraints through the audio API so management clients do not hard-code backend validation rules.

#### Scenario: Future adapter type is registered
- **WHEN** a future physical or virtual endpoint adapter type is registered
- **THEN** the management UI can present its schema without changing the desired-graph node catalogue

#### Scenario: Invalid configuration is submitted
- **WHEN** a required address, port, file, format, or type-specific value is invalid
- **THEN** the API rejects the write with field-specific diagnostics and leaves the current adapter unchanged

### Requirement: ROC receivers expose input endpoints
The system SHALL support ROC receiver adapters that bind configurable local source, repair, and control ports and expose received audio as a stable PipeWire `Audio/Source` endpoint.

#### Scenario: Create a network input
- **WHEN** a user creates and enables a ROC receiver with valid local address, ports, FEC, latency, and resampler settings
- **THEN** a source endpoint appears in runtime inventory and can be bound as an input in a desired graph

#### Scenario: ROC ports conflict
- **WHEN** the configured local ROC ports cannot be bound
- **THEN** the adapter enters an error state that identifies the conflicting configuration and no healthy endpoint is reported

### Requirement: ROC senders expose output endpoints
The system SHALL support ROC sender adapters that target configurable remote source, repair, and control ports and expose a stable PipeWire `Audio/Sink` endpoint.

#### Scenario: Create a network output
- **WHEN** a user creates and enables a ROC sender with valid remote address, ports, and FEC settings
- **THEN** a sink endpoint appears in runtime inventory and can be bound as an output in a desired graph

#### Scenario: Remote receiver is unavailable
- **WHEN** the configured remote receiver does not answer but the local ROC module remains operational
- **THEN** the UI distinguishes local adapter readiness from observed network activity instead of claiming end-to-end audio delivery

### Requirement: Debug file sources loop continuously
The system SHALL support a debug file source that reads a supported PCM audio file from the configured adapter-media root, exposes a stable PipeWire `Audio/Source`, and returns to the beginning after end-of-file until disabled or failed.

#### Scenario: File reaches its end
- **WHEN** an enabled debug source reaches the final audio frame
- **THEN** playback continues from the first frame without requiring user action and the same managed endpoint identity remains available

#### Scenario: Source file is unsupported
- **WHEN** the selected file cannot be decoded as a supported PCM format
- **THEN** activation is rejected or the adapter enters a clear error state without exposing a healthy source

### Requirement: Debug file recorders capture graph output
The system SHALL support a debug file recorder that exposes a stable PipeWire `Audio/Sink` and writes received PCM audio to a file under the configured adapter-media root using configured format, rate, channels, and channel positions.

#### Scenario: Record a route
- **WHEN** a desired graph routes audio into an enabled file recorder
- **THEN** received frames are written to the selected recording and current byte or duration progress is observable

#### Scenario: Recorder stops
- **WHEN** a user disables or restarts a recording adapter
- **THEN** the current output file is finalized before the endpoint is reported stopped

#### Scenario: Output already exists
- **WHEN** a recorder targets an existing file without explicit replacement permission
- **THEN** startup fails safely and the existing file is not modified

### Requirement: Media paths are constrained
File adapters SHALL accept only normalized paths beneath a configured adapter-media root and SHALL reject traversal, absolute paths, directories, unsupported file types, and inaccessible files.

#### Scenario: Path traversal is submitted
- **WHEN** a configuration contains a path that would escape the adapter-media root
- **THEN** the API rejects it without reading, creating, or overwriting that path

### Requirement: Adapter lifecycle is continuously reconciled
The active Open Cinema orchestrator SHALL start, observe, restart, and stop adapter runtime resources until they match the latest persistent enabled state and configuration, with bounded failure retries.

#### Scenario: Managed process exits
- **WHEN** an enabled adapter process exits unexpectedly
- **THEN** the adapter reports the exit and is retried using bounded backoff without creating duplicate processes

#### Scenario: Configuration changes
- **WHEN** an enabled adapter's runtime-affecting configuration changes
- **THEN** the old resource is stopped and one replacement is started with the new configuration

#### Scenario: Controller is shutting down
- **WHEN** the active orchestrator loses ownership or shuts down
- **THEN** every child resource it owns is stopped and no unmanaged adapter process is intentionally left behind

### Requirement: Adapter endpoints have stable correlation metadata
Every adapter-created PipeWire node SHALL carry stable Open Cinema ownership, adapter identity, node name, description, direction, and virtual or network classification metadata.

#### Scenario: PipeWire numeric ID changes
- **WHEN** an adapter is restarted and its PipeWire numeric node identifier changes
- **THEN** runtime inventory correlates the new node to the same adapter and logical endpoint selectors continue to match stable properties

#### Scenario: Adapter appears in discovery
- **WHEN** an adapter endpoint is observed through WirePlumber
- **THEN** device discovery labels it as a managed endpoint adapter, permits logical endpoint binding, and does not classify it as physical hardware or an in-graph processor

### Requirement: Adapter endpoints do not bypass desired routing
Managed endpoint adapters SHALL expose endpoints without implicitly connecting them to other audio nodes, changing defaults, or claiming unrelated links.

#### Scenario: File source starts
- **WHEN** a debug file source becomes ready
- **THEN** it remains unconnected until desired-graph reconciliation or an explicit authorized runtime action routes it

### Requirement: Users can manage adapters from the management console
The `apps/admin` management console SHALL provide a dedicated endpoint-adapter menu for listing, creating, editing, enabling, disabling, restarting, and inspecting ROC and debug-file adapters using existing UI components and without new project-specific CSS.

#### Scenario: User creates a ROC receiver
- **WHEN** the user completes the ROC receiver form
- **THEN** the UI saves the adapter, shows lifecycle progress, and links to its discovered endpoint once ready

#### Scenario: Adapter fails
- **WHEN** an adapter cannot start or loses its runtime endpoint
- **THEN** the menu shows its desired state, observed state, last error, retry state, and relevant diagnostics separately

### Requirement: Adapter APIs separate desired and observed state
The versioned audio API SHALL expose adapter type schemas, persistent adapter definitions, explicit lifecycle actions, and observed status with authentication, ownership filtering, optimistic concurrency, and problem responses.

#### Scenario: Concurrent edit conflicts
- **WHEN** a client updates an adapter using an outdated version
- **THEN** the API rejects the update with the current version and does not replace newer configuration

#### Scenario: Restart is requested
- **WHEN** an authorized user explicitly restarts an enabled adapter
- **THEN** the desired configuration remains unchanged while runtime generation and lifecycle status show the requested restart
