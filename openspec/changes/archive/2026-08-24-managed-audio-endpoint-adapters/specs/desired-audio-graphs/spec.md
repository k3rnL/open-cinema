## ADDED Requirements

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
