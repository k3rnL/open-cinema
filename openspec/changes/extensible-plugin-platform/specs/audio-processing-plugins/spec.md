## ADDED Requirements

### Requirement: Processing capabilities share the common plugin distribution identity
An installable distribution that contributes processing node types SHALL declare them as bounded
capabilities under the same stable plugin identity, compatibility, provenance, desired state, and
health record as its application, UI, automation, or managed-resource capabilities.

#### Scenario: Composite processing plugin is disabled
- **WHEN** an administrator disables a plugin that contributes processing nodes and administration pages
- **THEN** all of its contributions become unavailable together while saved graph configurations and plugin data remain preserved

#### Scenario: Processing-only distribution is installed
- **WHEN** a compatible plugin declares only processing capabilities
- **THEN** it can be installed and managed through the common plugin inventory without declaring an application route

### Requirement: Processing capabilities activate only for enabled plugins
Node schemas MAY remain available as preserved metadata for editing and diagnostics, but planning
and runtime hooks SHALL execute only when their owning plugin is compatible, enabled, loaded, and
healthy enough for the requested operation.

#### Scenario: Disabled processor remains in a graph
- **WHEN** a desired graph references a node owned by a disabled plugin
- **THEN** the graph remains editable, the node is explicitly unavailable, and validation and apply do not invoke its plugin hooks

## MODIFIED Requirements

### Requirement: Plugin failures are contained
A processing capability failure SHALL not prevent unrelated plugins, unrelated capabilities of the
same plugin when safely independent, API diagnostics, or runtime observation from operating. The
affected capability and graph node SHALL receive an explicit unavailable or error state, and a
distribution-wide failure SHALL disable all capabilities whose safety depends on it.

#### Scenario: Plugin import fails
- **WHEN** one optional plugin raises an exception during discovery
- **THEN** startup records the failure, disables its capabilities, and continues with unaffected capabilities and runtime observation

#### Scenario: One declared node schema is invalid
- **WHEN** a multi-capability plugin contains one invalid processing node declaration but its independent administration page remains valid
- **THEN** the invalid node capability is unavailable with a diagnostic while the safe independent page and plugin inventory remain accessible

### Requirement: General application plugins remain supported
The application SHALL provide versioned plugin capabilities for namespaced APIs, automations,
processing nodes, managed resources, managed audio sources, device integrations, and declarative
administration pages, subject to explicit contracts, compatibility checks, desired-state gating,
and failure isolation.

#### Scenario: Non-audio API plugin
- **WHEN** an enabled compatible plugin contributes application routes unrelated to the audio runtime
- **THEN** those routes register under its authenticated namespace independently from processing-node registration

#### Scenario: One distribution contributes several capability kinds
- **WHEN** a plugin contributes an API, administration page, and processing node under one manifest
- **THEN** the catalogue reports one plugin identity and preserves the specific contract and health of each capability

