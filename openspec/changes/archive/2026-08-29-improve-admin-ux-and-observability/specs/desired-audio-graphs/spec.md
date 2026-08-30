## MODIFIED Requirements

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

## ADDED Requirements

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
