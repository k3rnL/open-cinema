# Desired Audio Graphs Specification

## Purpose

Defines persistent, parameterized audio intent independently of transient runtime objects so users can build reusable configurations that remain meaningful while devices and processors appear, disappear, or change.

## Requirements

### Requirement: Desired graphs are persistent intent
The system SHALL persist each desired audio graph independently from the currently observed PipeWire graph, and SHALL NOT rewrite the desired graph merely because an endpoint or processor is unavailable.

#### Scenario: Referenced output is disconnected
- **WHEN** a saved graph references a logical headset that is currently unavailable
- **THEN** the saved graph and its endpoint reference remain unchanged
- **AND** the graph resolution reports the unavailable dependency and any selected fallback

#### Scenario: Runtime object identifiers change
- **WHEN** PipeWire recreates a node with a different runtime identifier
- **THEN** the desired graph continues to reference the logical endpoint rather than the former runtime identifier

### Requirement: Graphs use typed nodes and ports
The system SHALL describe graph nodes through registered node types with named, directed, typed ports and SHALL permit an edge only when its source and target ports are compatible.

#### Scenario: Compatible audio connection
- **WHEN** a user connects an audio-producing output port to a compatible audio-consuming input port
- **THEN** the graph accepts the edge

#### Scenario: Incompatible port connection
- **WHEN** a user connects ports with incompatible direction, media type, or required capabilities
- **THEN** the graph rejects the edge with a port-specific explanation

### Requirement: Graphs distinguish endpoints from processors
The system SHALL model endpoint references and processors as distinct node roles: endpoint references select durable input or output intent, while processors consume, transform or inspect, and emit audio within a route.

#### Scenario: Insert a managed processor
- **WHEN** a user places CamillaDSP or an adaptive decoder between compatible graph stages
- **THEN** the saved graph contains a processor node with typed ports, configuration, signal contracts, and lifecycle requirements rather than an endpoint reference

#### Scenario: Processor exposes runtime nodes
- **WHEN** a managed processor creates PipeWire nodes or streams
- **THEN** those runtime resources correlate to the processor instance without changing the processor into a logical hardware endpoint

#### Scenario: Processor is temporarily unavailable
- **WHEN** a saved graph references an unavailable processor type or unhealthy processor instance
- **THEN** the processor node and opaque configuration remain saved and resolution reports unavailable, waiting, degraded, or an allowed bypass

### Requirement: Graph parameters are declared and validated
The system SHALL allow graph and subgraph definitions to declare typed parameters with names, descriptions, defaults, constraints, and whether a value is required.

#### Scenario: Parameter override
- **WHEN** a graph instance overrides a declared parameter with a valid value
- **THEN** resolution uses the overridden value without changing the reusable definition

#### Scenario: Invalid parameter
- **WHEN** a parameter value violates its declared type or constraint
- **THEN** validation identifies the parameter and the violated constraint

### Requirement: Graphs support reusable subgraphs
The system SHALL allow a graph definition to contain instances of reusable subgraph definitions that expose only declared public ports and parameters.

#### Scenario: Reuse processing chain
- **WHEN** a user inserts the same room-processing subgraph into multiple graphs
- **THEN** each instance references the reusable definition and may provide independent parameter values

#### Scenario: Collapse subgraph
- **WHEN** a user views a graph containing a subgraph instance in collapsed mode
- **THEN** the UI presents the subgraph as one node with its public ports while preserving its internal definition

### Requirement: Subgraphs are versioned
The system SHALL assign immutable versions to published subgraph definitions and SHALL allow graph instances to pin a version or explicitly upgrade to a newer compatible version.

#### Scenario: Definition is updated
- **WHEN** a new version of a reused subgraph is published
- **THEN** existing graph instances continue using their pinned version until explicitly upgraded

#### Scenario: Incompatible upgrade
- **WHEN** an upgrade removes or changes a public port or required parameter used by an instance
- **THEN** the system blocks the upgrade and reports every incompatible binding

### Requirement: Graph revisions are editable without disrupting the active revision
The system SHALL create or reuse an editable draft on the first user mutation, SHALL persist subsequent draft mutations automatically, and SHALL keep another published revision selected for reconciliation until the user explicitly applies the draft.

#### Scenario: Edit active graph
- **WHEN** a user changes an active graph while viewing its published revision
- **THEN** the system creates or reuses a draft, applies the mutation to that draft, and leaves the active resolved plan unchanged

#### Scenario: First mutation occurs while draft creation is pending
- **WHEN** the user makes further graph changes before automatic draft creation completes
- **THEN** every local mutation is preserved in order and is applied to the created draft without reverting the editor

#### Scenario: Publish valid revision
- **WHEN** a user applies a valid draft revision
- **THEN** the latest saved local content becomes an immutable published revision and one atomic desired-state activation change

### Requirement: Structural validation is independent from availability
The system SHALL distinguish structural validity from runtime resolvability so an unavailable optional endpoint does not make a structurally correct graph invalid.

#### Scenario: Valid graph with unavailable endpoint
- **WHEN** all node, port, parameter, and subgraph contracts are valid but an endpoint is absent
- **THEN** structural validation succeeds and runtime resolution reports waiting or degraded state

#### Scenario: Unsupported cycle
- **WHEN** a graph contains a feedback cycle not explicitly supported by every involved node type
- **THEN** structural validation rejects the cycle and identifies its participating edges

### Requirement: Desired graph serialization is stable
The system SHALL expose a versioned serialization format for graph definitions, subgraph references, node parameters, endpoint selectors, conditions, and public-port bindings.

#### Scenario: Round-trip serialization
- **WHEN** a graph is exported and imported without modification
- **THEN** its semantic definition, subgraph versions, parameters, and selectors remain equivalent

#### Scenario: Unsupported schema version
- **WHEN** an imported graph uses an unsupported future schema version
- **THEN** the system rejects it without partially creating graph resources

### Requirement: Active graphs can be deactivated without losing their design
The system SHALL let an authorized user deactivate an active top-level graph while preserving its definition, draft and published revisions, layout, parameterization, and revision history. Activation and deactivation SHALL share one monotonic desired-state version and optimistic-concurrency contract.

#### Scenario: User deactivates an active graph
- **WHEN** the user confirms deactivation using the current activation version
- **THEN** the graph reports no active revision, its desired-state version advances, and every saved revision remains available for editing or later reactivation

#### Scenario: User has unsaved draft work
- **WHEN** an active graph with an independent draft is deactivated
- **THEN** the draft content is neither saved nor discarded by the deactivation operation

#### Scenario: Deactivation races with another desired-state change
- **WHEN** a client deactivates using an outdated activation version
- **THEN** the API rejects the request without disabling the newer desired state

#### Scenario: Deactivation is repeated
- **WHEN** a client repeats deactivation against an already disabled graph using its current version
- **THEN** the operation succeeds idempotently without advancing the version or deleting saved data

#### Scenario: User reactivates the graph
- **WHEN** a published revision of a disabled graph is activated with the current desired-state version
- **THEN** the same activation identity becomes enabled, the version advances, and normal graph reconciliation resumes

### Requirement: Published graph revisions remain directly applicable
The management console SHALL let a user apply an inactive existing published top-level graph revision independently from creating or editing a draft, and SHALL let the user deactivate an active graph. Apply and Deactivate SHALL be mutually exclusive in the graph list and published-revision view. A draft editor SHALL instead expose Apply changes as its single primary lifecycle action so an active graph can be updated without an unnecessary audio interruption.

#### Scenario: User applies from the graph list
- **WHEN** a top-level graph is inactive and has at least one published revision
- **THEN** its action column offers Apply for the latest published revision using the current desired-state version

#### Scenario: User opens an inactive published revision
- **WHEN** the graph editor is displaying an inactive published top-level revision rather than a draft
- **THEN** Apply remains available and editing the document implicitly starts a draft

#### Scenario: User opens an active graph
- **WHEN** the graph has an active revision
- **THEN** Deactivate is available and Apply is absent until deactivation or a distinct draft apply workflow becomes eligible

#### Scenario: User edits a graph that is already active
- **WHEN** an automatically saved draft is displayed while another revision remains active
- **THEN** the draft editor offers Apply changes without placing Deactivate beside it, and applying atomically replaces the active revision

#### Scenario: An independent draft exists
- **WHEN** the user applies a published revision from the graph list
- **THEN** that published revision is activated and the independent draft is neither published nor modified

#### Scenario: No published revision exists
- **WHEN** a graph contains only an initial draft
- **THEN** the graph list does not offer an Apply action until the draft is valid and applied through its editor

### Requirement: Every graph mutation participates in autosave
Node creation, deletion, movement, collapse state, edge creation or deletion, metadata, parameters, public ports, conditions, configuration values, subgraph bindings, and automatic layout SHALL all enter the same ordered autosave pipeline. A successful save response SHALL NOT replace newer local mutations with older canonical content.

#### Scenario: Move a node then edit a value
- **WHEN** the user moves a node and immediately changes one of its values
- **THEN** both the new position and value remain visible and are persisted in the resulting draft

#### Scenario: Save response arrives after another edit
- **WHEN** a save response for document version N arrives after the user has created local version N+1
- **THEN** the response advances the server version without resetting the N+1 local document

#### Scenario: User applies while autosave is pending
- **WHEN** the user selects Apply before the debounce or current save request completes
- **THEN** Apply waits for the newest local document to be saved before validation and publication

### Requirement: Autosave state is observable and recoverable
The graph editor SHALL expose stable states for saved, saving, pending changes, offline, conflict, and failed save. It SHALL retry safe transient failures with bounds, preserve the local document on failure, and require an explicit user choice before discarding either side of an optimistic-concurrency conflict.

#### Scenario: Network fails during autosave
- **WHEN** a draft save cannot reach the server
- **THEN** local edits remain in the editor, the status reports that changes are not yet saved, and retry does not duplicate or reorder mutations

#### Scenario: Another client updated the draft
- **WHEN** autosave receives an optimistic-concurrency conflict
- **THEN** live audio and the remote draft remain unchanged and the editor offers review, reload remote, or preserve local copy actions without silently selecting a winner

### Requirement: Graph layout is durable presentation state
Node coordinates, collapsed state, and viewport state SHALL round-trip as draft presentation data without changing graph semantics. Canonical validation or resolution SHALL NOT recalculate user positions, and runtime overlays SHALL NOT modify saved layout.

#### Scenario: User returns to a draft
- **WHEN** a user moves nodes, leaves the editor after autosave, and later reopens the draft
- **THEN** nodes and viewport are restored to the saved presentation state

#### Scenario: Runtime selection changes
- **WHEN** an endpoint connects or a processor health overlay changes
- **THEN** the observed overlay updates without moving desired graph nodes or marking the draft semantically changed
