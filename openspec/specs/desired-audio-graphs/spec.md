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
The system SHALL support editing a draft revision while another published revision remains selected for reconciliation.

#### Scenario: Edit active graph
- **WHEN** a user edits a graph that currently has a resolved plan
- **THEN** the system creates or updates a draft without changing the active resolved plan

#### Scenario: Publish valid revision
- **WHEN** a user publishes a valid draft revision
- **THEN** the revision becomes eligible for resolution as one atomic desired-state change

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
The management console SHALL let a user apply an existing published top-level graph revision independently from creating or editing a draft.

#### Scenario: User applies from the graph list
- **WHEN** a top-level graph has at least one published revision
- **THEN** its action column offers Apply for the latest published revision using the current desired-state version

#### Scenario: User opens a published revision
- **WHEN** the graph editor is displaying a published top-level revision rather than a draft
- **THEN** Apply remains available alongside Start draft

#### Scenario: An independent draft exists
- **WHEN** the user applies a published revision from the graph list
- **THEN** that published revision is activated and the independent draft is neither published nor modified

#### Scenario: No published revision exists
- **WHEN** a graph contains only an initial draft
- **THEN** the graph list does not offer an Apply action until a revision has been published
