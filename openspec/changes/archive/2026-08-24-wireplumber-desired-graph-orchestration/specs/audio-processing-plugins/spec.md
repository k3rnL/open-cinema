## Purpose

Defines a stable extension contract for audio processors and related graph capabilities while preventing plugins from competing with WirePlumber for device discovery or session ownership.

## ADDED Requirements

### Requirement: Processing plugins register graph node types
The system SHALL allow an installed processing plugin to register one or more uniquely identified node types with display metadata, version, category, fields, parameters, public ports, and capability constraints.

#### Scenario: Plugin registers a processor
- **WHEN** a valid processing plugin is discovered at startup
- **THEN** its node-type definitions are available to graph validation, APIs, and the UI schema catalogue

#### Scenario: Duplicate node type
- **WHEN** two plugins register the same node-type identifier and version incompatibly
- **THEN** plugin loading reports a conflict and does not silently replace either definition

### Requirement: Plugins do not provide audio runtimes
Processing plugins SHALL NOT replace WirePlumber discovery, inventory, default selection, volume, mute, or session graph observation.

#### Scenario: Plugin declares an audio backend
- **WHEN** a legacy plugin attempts to register an audio backend
- **THEN** the system rejects or ignores that capability with a migration diagnostic

### Requirement: Plugin schemas are serializable
Each processing node type SHALL expose a versioned machine-readable schema for editable fields, parameters, relations, ports, defaults, constraints, and conditional visibility.

#### Scenario: UI loads plugin schema
- **WHEN** the graph editor requests the node-type catalogue
- **THEN** it can render the processor without hard-coded knowledge of that plugin's model fields

### Requirement: Plugins participate in validation and planning
Each processing plugin SHALL be able to validate node configuration and adjacent signal contracts and SHALL contribute declarative requirements and actions to a resolved plan.

#### Scenario: Unsupported channel layout
- **WHEN** a processor accepts at most two channels but receives a six-channel signal
- **THEN** plugin validation reports the incompatibility or declares a supported adapter requirement

### Requirement: Runtime lifecycle is reconciliation-driven
Processing plugins SHALL expose idempotent prepare, activate, observe, reconfigure, deactivate, and cleanup semantics as applicable, and SHALL be invoked only through reconciliation.

#### Scenario: Reconciliation retries activation
- **WHEN** activation is retried after an uncertain worker outcome
- **THEN** the plugin recognizes an existing managed instance or safely creates exactly one instance

### Requirement: Plugins expose processor health and state
The system SHALL collect structured readiness, active configuration, observed input/output signal, managed resource identifiers, warnings, and failure details from processors.

#### Scenario: Processor becomes unhealthy
- **WHEN** a running processor reports failure or disappears
- **THEN** its health fact triggers route resolution and is visible in the resolved-plan explanation

### Requirement: Plugin failures are contained
A processing plugin failure SHALL not prevent unrelated plugins, API diagnostics, or runtime observation from operating, and the affected node SHALL receive an explicit unavailable or error state.

#### Scenario: Plugin import fails
- **WHEN** one optional plugin raises an exception during discovery
- **THEN** startup records the failure, disables its node types, and continues with unaffected capabilities

### Requirement: Plugin upgrades preserve graph compatibility
Node-type definitions SHALL declare configuration schema versions and migrations or incompatibility boundaries for saved graph instances.

#### Scenario: Compatible plugin upgrade
- **WHEN** a plugin supplies a migration from a saved node schema version
- **THEN** the user can preview and apply the migrated configuration without losing unrelated graph data

#### Scenario: Plugin removed
- **WHEN** a graph references a node type whose plugin is no longer installed
- **THEN** the graph remains loadable and editable, marks the node unavailable, and preserves its opaque configuration for recovery

### Requirement: General application plugins remain supported
The application SHALL retain extension points for non-audio-runtime capabilities such as APIs, models, automations, and device integrations, subject to explicit plugin contracts and isolation.

#### Scenario: Non-audio API plugin
- **WHEN** an installed plugin contributes application routes unrelated to the audio runtime
- **THEN** those routes continue to register independently from processing-node registration
